"""フレンド状況確認。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
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
from app.services import app_config_service, vrchat_session_service, vrchat_sync_service
from app.services.vrchat.client import VRChatAPIError, VRChatClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/friends", dependencies=[Depends(get_current_user)])

_HISTORY_PAGE_SIZE = 50


async def _fetch_friends(
    db: AsyncSession, *, group_id: int | None, only_online: bool
) -> list[Friend]:
    query = select(Friend)
    if group_id is not None:
        query = query.join(
            FriendGroupMembership, FriendGroupMembership.friend_id == Friend.id
        ).where(FriendGroupMembership.group_id == group_id)
    if only_online:
        query = query.where(Friend.is_online.is_(True))
    query = query.order_by(Friend.is_online.desc(), Friend.display_name)
    result = await db.execute(query)
    return list(result.scalars().unique().all())


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
    group_id: int | None = None,
    only_online: bool = False,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    friends = await _fetch_friends(db, group_id=group_id, only_online=only_online)
    groups = await _fetch_groups(db)
    return templates.TemplateResponse(
        request,
        "friends/list.html",
        {
            "friends": friends,
            "groups": groups,
            "selected_group_id": group_id,
            "only_online": only_online,
        },
    )


@router.get("/partials/list", response_class=HTMLResponse)
async def friends_list_partial(
    request: Request,
    group_id: int | None = None,
    only_online: bool = False,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    friends = await _fetch_friends(db, group_id=group_id, only_online=only_online)
    return templates.TemplateResponse(request, "friends/_list.html", {"friends": friends})


@router.get("/{friend_id}", response_class=HTMLResponse)
async def friend_detail_page(
    request: Request, friend_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    friend = await db.get(Friend, friend_id)
    if friend is None:
        return templates.TemplateResponse(
            request, "friends/not_found.html", status_code=404
        )
    pref = await db.get(FriendNotificationPref, friend_id)
    result = await db.execute(
        select(FriendPresenceEvent)
        .where(FriendPresenceEvent.friend_id == friend_id)
        .order_by(FriendPresenceEvent.occurred_at.desc())
        .limit(_HISTORY_PAGE_SIZE)
    )
    events = result.scalars().all()
    groups = await _fetch_groups(db)
    friend_group_ids = await _fetch_friend_group_ids(db, friend_id)
    return templates.TemplateResponse(
        request,
        "friends/detail.html",
        {
            "friend": friend,
            "pref": pref,
            "events": events,
            "groups": groups,
            "friend_group_ids": friend_group_ids,
        },
    )


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

    friends = await _fetch_friends(db, group_id=None, only_online=False)
    return templates.TemplateResponse(
        request,
        "friends/_sync_result.html",
        {"success": True, "message": "同期が完了しました。", "friends": friends},
    )
