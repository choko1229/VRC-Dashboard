"""フレンドの状態管理（DB更新）とVRChatからの同期処理。

Pipelineのイベントハンドリング（app.services.vrchat.pipeline）と、
REST APIによる初回ブートストラップ/手動再同期の両方から呼び出される。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecretCipher
from app.models.friend import Friend
from app.models.friend_group import FriendGroup
from app.models.friend_group_membership import FriendGroupMembership
from app.models.friend_notification_pref import FriendNotificationPref
from app.models.friend_presence_event import FriendPresenceEvent
from app.notifications.base import NotificationPayload, NotificationSender
from app.schemas.vrchat import (
    VRChatFavorite,
    VRChatFavoriteGroup,
    VRChatGroupSummary,
    VRChatUser,
    VRChatWorld,
    parse_world_id_from_location,
)
from app.services import app_config_service, vrchat_session_service
from app.services.vrchat.client import VRChatAPIError, VRChatClient

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")
_WEEKDAY_LABELS_JA = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]


@dataclass
class ActivityStats:
    """フレンド詳細「アクティビティ」タブ用の、曜日×時間帯のオンライン確認回数集計。"""

    grid: list[list[int]]  # grid[曜日(0=月...6=日)][時(0-23)] = 確認回数
    max_count: int
    total_events: int
    most_active_weekday: str | None
    peak_hour_range: str | None


async def compute_activity_stats(db: AsyncSession, friend_id: int) -> ActivityStats:
    """保存済みのオンライン化イベント(friend_presence_event)から活動傾向を集計する。

    表示はJST(Asia/Tokyo)基準（本アプリの想定利用者に合わせた固定変換。
    ユーザーごとのタイムゾーン設定は現状持たない）。
    """
    result = await db.execute(
        select(FriendPresenceEvent.occurred_at).where(
            FriendPresenceEvent.friend_id == friend_id,
            FriendPresenceEvent.event_type == "online",
        )
    )
    occurred_ats = result.scalars().all()

    grid = [[0] * 24 for _ in range(7)]
    for occurred_at in occurred_ats:
        # SQLiteはタイムゾーン情報を保持しないため、読み出し時naiveになったdatetimeは
        # 書き込み時と同じUTCとして扱ってから変換する（app.services.session_service参照）。
        aware = occurred_at if occurred_at.tzinfo is not None else occurred_at.replace(tzinfo=UTC)
        local = aware.astimezone(_JST)
        grid[local.weekday()][local.hour] += 1

    total_events = len(occurred_ats)
    if total_events == 0:
        return ActivityStats(
            grid=grid,
            max_count=0,
            total_events=0,
            most_active_weekday=None,
            peak_hour_range=None,
        )

    weekday_totals = [sum(row) for row in grid]
    most_active_weekday = _WEEKDAY_LABELS_JA[weekday_totals.index(max(weekday_totals))]

    hour_totals = [sum(grid[w][h] for w in range(7)) for h in range(24)]
    peak_hour = hour_totals.index(max(hour_totals))
    peak_hour_range = f"{peak_hour:02d}:00-{(peak_hour + 1) % 24:02d}:00"

    return ActivityStats(
        grid=grid,
        max_count=max(max(row) for row in grid),
        total_events=total_events,
        most_active_weekday=most_active_weekday,
        peak_hour_range=peak_hour_range,
    )


async def _get_or_create_friend(db: AsyncSession, vrchat_user_id: str, display_name: str) -> Friend:
    result = await db.execute(select(Friend).where(Friend.vrchat_user_id == vrchat_user_id))
    friend = result.scalar_one_or_none()
    if friend is None:
        friend = Friend(vrchat_user_id=vrchat_user_id, display_name=display_name)
        db.add(friend)
        await db.flush()
    return friend


async def _get_notification_pref(db: AsyncSession, friend_id: int) -> FriendNotificationPref | None:
    return await db.get(FriendNotificationPref, friend_id)


async def _maybe_notify(
    sender: NotificationSender,
    pref: FriendNotificationPref | None,
    *,
    should_notify: bool,
    payload: NotificationPayload,
) -> None:
    if pref is None or not should_notify:
        return
    await sender.send(payload)


async def bootstrap_friends_from_vrchat(
    db: AsyncSession, *, online_friends: list[VRChatUser], offline_friends: list[VRChatUser]
) -> None:
    """REST APIの初回取得結果でfriendテーブル全体を作り直す（is_onlineも含めて確定させる）。"""
    now = datetime.now(UTC)

    for vrchat_user, is_online in (
        *((u, True) for u in online_friends),
        *((u, False) for u in offline_friends),
    ):
        friend = await _get_or_create_friend(db, vrchat_user.id, vrchat_user.display_name)
        friend.display_name = vrchat_user.display_name
        friend.is_online = is_online
        friend.activity_status = vrchat_user.status
        friend.status_message = vrchat_user.status_description
        if is_online:
            # VRChat APIが"state"を返さない/想定外の値の場合でも、is_online=Trueである以上
            # 最低限"online"扱いにする（"same instance"判定等が壊れないようにする）。
            valid_state = vrchat_user.state in ("online", "active")
            friend.online_state = vrchat_user.state if valid_state else "online"
        else:
            friend.online_state = "offline"
        friend.current_avatar_thumbnail_url = vrchat_user.current_avatar_thumbnail_image_url
        if is_online:
            world_id = parse_world_id_from_location(vrchat_user.location)
            friend.current_world_id = world_id
            friend.current_location = vrchat_user.location
            friend.last_seen_online_at = now
        else:
            friend.current_world_id = None
            friend.current_world_name = None
            friend.current_location = None
        friend.last_updated_at = now

    await db.commit()
    logger.info(
        "フレンド一覧を同期しました (online=%d, offline=%d)",
        len(online_friends),
        len(offline_friends),
    )


async def sync_favorite_groups(
    db: AsyncSession, *, groups: list[VRChatFavoriteGroup], favorites: list[VRChatFavorite]
) -> None:
    """VRChatのお気に入りグループ・所属関係をDBへ反映する（syncedグループのみ全置換）。"""
    group_name_to_id: dict[str, int] = {}

    for group in groups:
        result = await db.execute(
            select(FriendGroup).where(FriendGroup.vrchat_group_id == group.id)
        )
        row = result.scalar_one_or_none()
        display_name = group.display_name or group.name
        if row is None:
            row = FriendGroup(
                vrchat_group_id=group.id, name=display_name, source="synced"
            )
            db.add(row)
            await db.flush()
        else:
            row.name = display_name
        group_name_to_id[group.name] = row.id

    # syncedグループのメンバーシップは全消去してから作り直す（脱退・変更を確実に反映するため）。
    synced_group_ids = list(group_name_to_id.values())
    if synced_group_ids:
        await db.execute(
            delete(FriendGroupMembership).where(
                FriendGroupMembership.group_id.in_(synced_group_ids)
            )
        )

    for favorite in favorites:
        result = await db.execute(
            select(Friend).where(Friend.vrchat_user_id == favorite.favorite_id)
        )
        friend = result.scalar_one_or_none()
        if friend is None:
            continue
        for tag in favorite.tags:
            group_id = group_name_to_id.get(tag)
            if group_id is None:
                continue
            db.add(FriendGroupMembership(friend_id=friend.id, group_id=group_id))

    await db.commit()


async def handle_friend_online(
    db: AsyncSession,
    sender: NotificationSender,
    *,
    vrchat_user_id: str,
    display_name: str,
    location: str | None,
    world_name: str | None,
) -> None:
    friend = await _get_or_create_friend(db, vrchat_user_id, display_name)
    friend.display_name = display_name
    friend.is_online = True
    friend.online_state = "online"
    world_id = parse_world_id_from_location(location)
    friend.current_world_id = world_id
    friend.current_world_name = world_name
    friend.current_location = location
    now = datetime.now(UTC)
    friend.last_seen_online_at = now
    friend.last_updated_at = now

    db.add(
        FriendPresenceEvent(
            friend_id=friend.id,
            event_type="online",
            world_id=world_id,
            world_name=world_name,
            location=location,
            occurred_at=now,
        )
    )
    await db.commit()

    pref = await _get_notification_pref(db, friend.id)
    await _maybe_notify(
        sender,
        pref,
        should_notify=pref.notify_on_online if pref else False,
        payload=NotificationPayload(
            type="friend_online",
            friend_vrchat_user_id=vrchat_user_id,
            friend_display_name=display_name,
            world_name=world_name,
            occurred_at=now,
            message=f"{display_name} がオンラインになりました。",
        ),
    )


async def handle_friend_active(
    db: AsyncSession, sender: NotificationSender, *, vrchat_user_id: str, display_name: str
) -> None:
    """friend-activeイベント: 接続中だがワールドに滞在していない（Web/メニュー等）状態。"""
    friend = await _get_or_create_friend(db, vrchat_user_id, display_name)
    friend.display_name = display_name
    was_online = friend.is_online
    friend.is_online = True
    friend.online_state = "active"
    friend.current_world_id = None
    friend.current_world_name = None
    friend.current_location = None
    now = datetime.now(UTC)
    friend.last_seen_online_at = now
    friend.last_updated_at = now

    db.add(FriendPresenceEvent(friend_id=friend.id, event_type="online", occurred_at=now))
    await db.commit()

    if was_online:
        return
    pref = await _get_notification_pref(db, friend.id)
    await _maybe_notify(
        sender,
        pref,
        should_notify=pref.notify_on_online if pref else False,
        payload=NotificationPayload(
            type="friend_online",
            friend_vrchat_user_id=vrchat_user_id,
            friend_display_name=display_name,
            world_name=None,
            occurred_at=now,
            message=f"{display_name} がオンラインになりました。",
        ),
    )


async def handle_friend_offline(
    db: AsyncSession, sender: NotificationSender, *, vrchat_user_id: str, display_name: str
) -> None:
    friend = await _get_or_create_friend(db, vrchat_user_id, display_name)
    friend.is_online = False
    friend.online_state = "offline"
    friend.current_world_id = None
    friend.current_world_name = None
    friend.current_location = None
    now = datetime.now(UTC)
    friend.last_updated_at = now

    db.add(
        FriendPresenceEvent(friend_id=friend.id, event_type="offline", occurred_at=now)
    )
    await db.commit()

    pref = await _get_notification_pref(db, friend.id)
    await _maybe_notify(
        sender,
        pref,
        should_notify=pref.notify_on_offline if pref else False,
        payload=NotificationPayload(
            type="friend_offline",
            friend_vrchat_user_id=vrchat_user_id,
            friend_display_name=friend.display_name,
            world_name=None,
            occurred_at=now,
            message=f"{friend.display_name} がオフラインになりました。",
        ),
    )


async def handle_friend_location_change(
    db: AsyncSession,
    sender: NotificationSender,
    *,
    vrchat_user_id: str,
    display_name: str,
    location: str | None,
    world_name: str | None,
) -> None:
    friend = await _get_or_create_friend(db, vrchat_user_id, display_name)
    world_id = parse_world_id_from_location(location)
    friend.is_online = True
    friend.online_state = "online"
    friend.current_world_id = world_id
    friend.current_world_name = world_name
    friend.current_location = location
    now = datetime.now(UTC)
    friend.last_updated_at = now

    db.add(
        FriendPresenceEvent(
            friend_id=friend.id,
            event_type="location_change",
            world_id=world_id,
            world_name=world_name,
            location=location,
            occurred_at=now,
        )
    )
    await db.commit()

    pref = await _get_notification_pref(db, friend.id)
    await _maybe_notify(
        sender,
        pref,
        should_notify=pref.notify_on_world_change if pref else False,
        payload=NotificationPayload(
            type="friend_world_change",
            friend_vrchat_user_id=vrchat_user_id,
            friend_display_name=friend.display_name,
            world_name=world_name,
            occurred_at=now,
            message=f"{friend.display_name} が「{world_name or '不明なワールド'}」に移動しました。",
        ),
    )


async def handle_friend_status_update(db: AsyncSession, *, vrchat_user: VRChatUser) -> None:
    """statusDescription/表示名/サムネイル等の属性更新。ステータス・アバターの変化はフィード用に記録する。"""
    friend = await _get_or_create_friend(db, vrchat_user.id, vrchat_user.display_name)
    previous_status = friend.activity_status
    previous_avatar_url = friend.current_avatar_thumbnail_url
    now = datetime.now(UTC)

    friend.display_name = vrchat_user.display_name
    friend.activity_status = vrchat_user.status
    friend.status_message = vrchat_user.status_description
    friend.current_avatar_thumbnail_url = vrchat_user.current_avatar_thumbnail_image_url
    friend.last_updated_at = now

    if previous_status != vrchat_user.status:
        db.add(
            FriendPresenceEvent(
                friend_id=friend.id,
                event_type="status_change",
                status=vrchat_user.status,
                previous_status=previous_status,
                occurred_at=now,
            )
        )
    # avatar_thumbnail_urlが未取得(None)から初めて取得できた場合は「変更」ではないため記録しない。
    if (
        previous_avatar_url is not None
        and previous_avatar_url != vrchat_user.current_avatar_thumbnail_image_url
    ):
        db.add(
            FriendPresenceEvent(friend_id=friend.id, event_type="avatar_change", occurred_at=now)
        )

    await db.commit()


async def _build_client_from_session(
    db: AsyncSession, cipher: SecretCipher
) -> VRChatClient | None:
    """保存済みのVRChatセッションからAPIクライアントを組み立てる。未連携ならNone。

    呼び出し側は必ずtry/finallyで`close()`すること。
    """
    cookies = await vrchat_session_service.get_decrypted_cookies(db, cipher)
    if cookies is None:
        return None
    auth_cookie, two_factor_cookie = cookies
    user_agent = await app_config_service.get_vrchat_user_agent(db)
    return VRChatClient(
        user_agent=user_agent, auth_cookie=auth_cookie, two_factor_cookie=two_factor_cookie
    )


async def fetch_live_profile(
    db: AsyncSession, cipher: SecretCipher, *, vrchat_user_id: str
) -> VRChatUser | None:
    """フレンド詳細モーダル用に、bio/アカウント作成日/会員ランク等のフルプロフィールを
    VRChatから都度取得する。VRChat未連携時や通信失敗時はNoneを返し、呼び出し側は
    ローカルに保存済みの情報のみで表示を続行する。
    """
    client = await _build_client_from_session(db, cipher)
    if client is None:
        return None
    try:
        return await client.get_user(vrchat_user_id)
    except VRChatAPIError:
        logger.warning("フレンドのフルプロフィール取得に失敗しました: %s", vrchat_user_id)
        return None
    finally:
        await client.close()


@dataclass
class GroupsOverview:
    """フレンド詳細「グループ」タブ用。フレンドが公開しているグループと、
    自分（ダッシュボード操作者）とのグループIDの重なりをまとめたもの。
    """

    friend_groups: list[VRChatGroupSummary]
    common_group_ids: set[str]


async def fetch_groups_overview(
    db: AsyncSession, cipher: SecretCipher, *, vrchat_user_id: str
) -> GroupsOverview | None:
    client = await _build_client_from_session(db, cipher)
    if client is None:
        return None
    try:
        friend_groups = await client.get_user_groups(vrchat_user_id)

        common_group_ids: set[str] = set()
        session = await vrchat_session_service.get_active_session(db)
        if session is not None:
            try:
                self_groups = await client.get_user_groups(session.vrchat_user_id)
                self_group_ids = {g.group_id for g in self_groups}
                common_group_ids = {g.group_id for g in friend_groups} & self_group_ids
            except VRChatAPIError:
                pass  # 自分のグループ一覧が取れなくても、相手のグループ一覧は表示を続ける

        return GroupsOverview(friend_groups=friend_groups, common_group_ids=common_group_ids)
    except VRChatAPIError:
        logger.warning("フレンドのグループ一覧取得に失敗しました: %s", vrchat_user_id)
        return None
    finally:
        await client.close()


async def fetch_user_worlds(
    db: AsyncSession, cipher: SecretCipher, *, vrchat_user_id: str
) -> list[VRChatWorld] | None:
    """フレンドが公開しているワールド一覧を取得する。取得不可の場合はNone。"""
    client = await _build_client_from_session(db, cipher)
    if client is None:
        return None
    try:
        return await client.get_user_worlds(vrchat_user_id)
    except VRChatAPIError:
        logger.warning("フレンドのワールド一覧取得に失敗しました: %s", vrchat_user_id)
        return None
    finally:
        await client.close()
