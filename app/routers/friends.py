"""フレンド状況確認。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_cipher, get_current_user
from app.core.security import SecretCipher
from app.core.templating import templates
from app.db.session import get_db
from app.models.friend import Friend
from app.models.friend_group import FriendGroup
from app.models.friend_group_membership import FriendGroupMembership
from app.models.friend_notification_pref import FriendNotificationPref
from app.models.friend_presence_event import FriendPresenceEvent
from app.schemas.vrchat import parse_trust_rank, resolve_profile_image_url
from app.services import (
    app_config_service,
    friends_service,
    sidebar_service,
    vrchat_session_service,
    vrchat_sync_service,
)
from app.services.sidebar_service import SameInstanceGroup
from app.services.vrchat.client import VRChatAPIError, VRChatClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/friends", dependencies=[Depends(get_current_user)])

_HISTORY_PAGE_SIZE = 50


@dataclass
class FriendSections:
    """フレンド一覧を「お気に入り／オンライン／オフライン」に区分した結果。

    お気に入り（いずれかのグループに所属）は状態を問わず最優先で分類し、
    残りをオンライン状態（online/active）かオフラインかで振り分ける。
    オンライン区分の中では、自分と同じインスタンスにいるフレンドを別枠にまとめる。
    """

    favorites: list[Friend]
    same_instance: SameInstanceGroup | None
    online: list[Friend]
    offline: list[Friend]


async def _fetch_friend_sections(db: AsyncSession, cipher: SecretCipher) -> FriendSections:
    all_friends_result = await db.execute(select(Friend).order_by(Friend.display_name))
    all_friends = list(all_friends_result.scalars().all())

    favorite_ids_result = await db.execute(select(FriendGroupMembership.friend_id).distinct())
    favorite_ids = set(favorite_ids_result.scalars().all())

    sidebar_groups = await sidebar_service.get_friend_sidebar_groups(db, cipher)
    same_instance = sidebar_groups.same_instance
    same_instance_ids: set[int] = set()
    if same_instance is not None:
        non_favorite = [f for f in same_instance.friends if f.id not in favorite_ids]
        if non_favorite:
            same_instance = replace(
                same_instance, friends=non_favorite, friend_count=len(non_favorite)
            )
            same_instance_ids = {f.id for f in non_favorite}
        else:
            same_instance = None

    favorites = [f for f in all_friends if f.id in favorite_ids]
    online = [
        f
        for f in all_friends
        if f.id not in favorite_ids
        and f.id not in same_instance_ids
        and f.online_state != "offline"
    ]
    offline = [
        f for f in all_friends if f.id not in favorite_ids and f.online_state == "offline"
    ]
    return FriendSections(
        favorites=favorites, same_instance=same_instance, online=online, offline=offline
    )


async def _fetch_groups(db: AsyncSession) -> list[FriendGroup]:
    result = await db.execute(
        select(FriendGroup).order_by(FriendGroup.sort_order, FriendGroup.name)
    )
    return list(result.scalars().all())


async def _fetch_friend_group_ids(db: AsyncSession, friend_id: int) -> set[int]:
    result = await db.execute(
        select(FriendGroupMembership.group_id).where(
            FriendGroupMembership.friend_id == friend_id
        )
    )
    return set(result.scalars().all())


@router.get("", response_class=HTMLResponse)
async def friends_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    sections = await _fetch_friend_sections(db, cipher)
    return templates.TemplateResponse(request, "friends/list.html", {"sections": sections})


async def _build_friend_detail_context(
    db: AsyncSession, cipher: SecretCipher, friend_id: int
) -> dict[str, object] | None:
    friend = await db.get(Friend, friend_id)
    if friend is None:
        return None
    pref = await db.get(FriendNotificationPref, friend_id)
    result = await db.execute(
        select(FriendPresenceEvent)
        .where(FriendPresenceEvent.friend_id == friend_id)
        .order_by(FriendPresenceEvent.occurred_at.desc())
        .limit(_HISTORY_PAGE_SIZE)
    )
    events = result.scalars().all()
    online_event_count = (
        await db.execute(
            select(func.count())
            .select_from(FriendPresenceEvent)
            .where(
                FriendPresenceEvent.friend_id == friend_id,
                FriendPresenceEvent.event_type == "online",
            )
        )
    ).scalar_one()
    groups = await _fetch_groups(db)
    friend_group_ids = await _fetch_friend_group_ids(db, friend_id)

    # bio/アカウント作成日/会員ランク等はフレンド一覧の簡易オブジェクトに含まれないため、
    # モーダル表示のたびにVRChatから都度取得する（未連携/通信失敗時はNoneのまま続行）。
    live_profile = await friends_service.fetch_live_profile(
        db, cipher, vrchat_user_id=friend.vrchat_user_id
    )
    trust_rank = parse_trust_rank(live_profile.tags) if live_profile else None
    profile_image_url = (
        resolve_profile_image_url(live_profile)
        if live_profile
        else friend.current_avatar_thumbnail_url
    )

    return {
        "friend": friend,
        "pref": pref,
        "events": events,
        "online_event_count": online_event_count,
        "groups": groups,
        "friend_group_ids": friend_group_ids,
        "live_profile": live_profile,
        "trust_rank": trust_rank,
        "profile_image_url": profile_image_url,
    }


@router.get("/{friend_id}/modal", response_class=HTMLResponse)
async def friend_detail_modal(
    request: Request,
    friend_id: int,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    """フレンド一覧のカードクリックでモーダル表示するための、ナビ無しの断片。"""
    context = await _build_friend_detail_context(db, cipher, friend_id)
    if context is None:
        return templates.TemplateResponse(
            request, "friends/_not_found_modal.html", status_code=404
        )
    return templates.TemplateResponse(request, "friends/_detail_content.html", context)


@router.get("/{friend_id}", response_class=HTMLResponse)
async def friend_detail_page(
    request: Request,
    friend_id: int,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    context = await _build_friend_detail_context(db, cipher, friend_id)
    if context is None:
        return templates.TemplateResponse(
            request, "friends/not_found.html", status_code=404
        )
    return templates.TemplateResponse(request, "friends/detail.html", context)


@router.post("/{friend_id}/notifications", response_class=HTMLResponse)
async def update_friend_notifications(
    request: Request,
    friend_id: int,
    notify_on_online: bool = Form(False),
    notify_on_offline: bool = Form(False),
    notify_on_world_change: bool = Form(False),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    pref = await db.get(FriendNotificationPref, friend_id)
    if pref is None:
        pref = FriendNotificationPref(friend_id=friend_id)
        db.add(pref)
    pref.notify_on_online = notify_on_online
    pref.notify_on_offline = notify_on_offline
    pref.notify_on_world_change = notify_on_world_change
    await db.commit()
    return templates.TemplateResponse(request, "friends/_notification_form.html", {"pref": pref})


@router.get("/groups/manage", response_class=HTMLResponse)
async def manage_groups_page(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    groups = await _fetch_groups(db)
    return templates.TemplateResponse(request, "friends/groups.html", {"groups": groups})


@router.post("/groups", response_class=HTMLResponse)
async def create_local_group(
    request: Request, name: str = Form(...), db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    db.add(FriendGroup(name=name, source="local"))
    await db.commit()
    groups = await _fetch_groups(db)
    return templates.TemplateResponse(request, "friends/_groups_list.html", {"groups": groups})


@router.delete("/groups/{group_id}", response_class=HTMLResponse)
async def delete_local_group(
    request: Request, group_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    group = await db.get(FriendGroup, group_id)
    if group is not None and group.source == "local":
        await db.delete(group)
        await db.commit()
    groups = await _fetch_groups(db)
    return templates.TemplateResponse(request, "friends/_groups_list.html", {"groups": groups})


@router.post("/{friend_id}/groups/{group_id}", response_class=HTMLResponse)
async def add_friend_to_group(
    request: Request, friend_id: int, group_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    existing = await db.get(FriendGroupMembership, (friend_id, group_id))
    if existing is None:
        db.add(FriendGroupMembership(friend_id=friend_id, group_id=group_id))
        await db.commit()
    friend = await db.get(Friend, friend_id)
    groups = await _fetch_groups(db)
    friend_group_ids = await _fetch_friend_group_ids(db, friend_id)
    return templates.TemplateResponse(
        request,
        "friends/_friend_groups.html",
        {"friend": friend, "groups": groups, "friend_group_ids": friend_group_ids},
    )


@router.delete("/{friend_id}/groups/{group_id}", response_class=HTMLResponse)
async def remove_friend_from_group(
    request: Request, friend_id: int, group_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    membership = await db.get(FriendGroupMembership, (friend_id, group_id))
    if membership is not None:
        await db.delete(membership)
        await db.commit()
    friend = await db.get(Friend, friend_id)
    groups = await _fetch_groups(db)
    friend_group_ids = await _fetch_friend_group_ids(db, friend_id)
    return templates.TemplateResponse(
        request,
        "friends/_friend_groups.html",
        {"friend": friend, "groups": groups, "friend_group_ids": friend_group_ids},
    )


@router.post("/sync", response_class=HTMLResponse)
async def manual_sync(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    cookies = await vrchat_session_service.get_decrypted_cookies(db, cipher)
    if cookies is None:
        return templates.TemplateResponse(
            request,
            "friends/_sync_result.html",
            {"success": False, "message": "VRChatと連携していません。"},
        )

    auth_cookie, two_factor_cookie = cookies
    user_agent = await app_config_service.get_vrchat_user_agent(db)
    client = VRChatClient(
        user_agent=user_agent,
        auth_cookie=auth_cookie,
        two_factor_cookie=two_factor_cookie,
    )
    try:
        await vrchat_sync_service.full_friends_sync(db, client)
    except VRChatAPIError as exc:
        return templates.TemplateResponse(
            request,
            "friends/_sync_result.html",
            {"success": False, "message": f"同期に失敗しました: {exc}"},
        )
    finally:
        await client.close()

    return templates.TemplateResponse(
        request,
        "friends/_sync_result.html",
        {"success": True, "message": "同期が完了しました。"},
    )
