"""フレンドの状態管理（DB更新）とVRChatからの同期処理。

Pipelineのイベントハンドリング（app.services.vrchat.pipeline）と、
REST APIによる初回ブートストラップ/手動再同期の両方から呼び出される。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.friend import Friend
from app.models.friend_group import FriendGroup
from app.models.friend_group_membership import FriendGroupMembership
from app.models.friend_notification_pref import FriendNotificationPref
from app.models.friend_presence_event import FriendPresenceEvent
from app.notifications.base import NotificationPayload, NotificationSender
from app.schemas.vrchat import (
    VRChatFavorite,
    VRChatFavoriteGroup,
    VRChatUser,
    parse_world_id_from_location,
)

logger = logging.getLogger(__name__)


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
    """statusDescription/表示名/サムネイル等、状態変化を伴わない属性更新。"""
    friend = await _get_or_create_friend(db, vrchat_user.id, vrchat_user.display_name)
    friend.display_name = vrchat_user.display_name
    friend.activity_status = vrchat_user.status
    friend.current_avatar_thumbnail_url = vrchat_user.current_avatar_thumbnail_image_url
    friend.last_updated_at = datetime.now(UTC)
    await db.commit()
