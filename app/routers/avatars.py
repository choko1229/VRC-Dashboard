"""アバター準備状況チェック。"""

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
from app.models.avatar import Avatar
from app.models.avatar_tag import AvatarTag
from app.models.tag import Tag
from app.services import (
    app_config_service,
    avatars_service,
    vrchat_session_service,
    vrchat_sync_service,
)
from app.services.vrchat.client import VRChatAPIError, VRChatClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/avatars", dependencies=[Depends(get_current_user)])


async def _fetch_avatars(db: AsyncSession, *, tag_id: int | None) -> list[Avatar]:
    query = select(Avatar)
    if tag_id is not None:
        query = query.join(AvatarTag, AvatarTag.avatar_id == Avatar.id).where(
            AvatarTag.tag_id == tag_id
        )
    query = query.order_by(Avatar.name)
    result = await db.execute(query)
    return list(result.scalars().unique().all())


async def _fetch_tags(db: AsyncSession) -> list[Tag]:
    result = await db.execute(select(Tag).order_by(Tag.name))
    return list(result.scalars().all())


async def _fetch_avatar_tags_map(db: AsyncSession, avatar_ids: list[int]) -> dict[int, list[Tag]]:
    if not avatar_ids:
        return {}
    result = await db.execute(
        select(AvatarTag.avatar_id, Tag)
        .join(Tag, Tag.id == AvatarTag.tag_id)
        .where(AvatarTag.avatar_id.in_(avatar_ids))
    )
    mapping: dict[int, list[Tag]] = {avatar_id: [] for avatar_id in avatar_ids}
    for avatar_id, tag in result.all():
        mapping[avatar_id].append(tag)
    return mapping


@router.get("", response_class=HTMLResponse)
async def avatars_page(
    request: Request, tag_id: int | None = None, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    avatars = await _fetch_avatars(db, tag_id=tag_id)
    tags = await _fetch_tags(db)
    avatar_tags_map = await _fetch_avatar_tags_map(db, [a.id for a in avatars])
    return templates.TemplateResponse(
        request,
        "avatars/list.html",
        {
            "avatars": avatars,
            "tags": tags,
            "avatar_tags_map": avatar_tags_map,
            "selected_tag_id": tag_id,
        },
    )


@router.get("/partials/list", response_class=HTMLResponse)
async def avatars_list_partial(
    request: Request, tag_id: int | None = None, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    avatars = await _fetch_avatars(db, tag_id=tag_id)
    avatar_tags_map = await _fetch_avatar_tags_map(db, [a.id for a in avatars])
    return templates.TemplateResponse(
        request, "avatars/_list.html", {"avatars": avatars, "avatar_tags_map": avatar_tags_map}
    )


@router.get("/{avatar_id}", response_class=HTMLResponse)
async def avatar_detail_page(
    request: Request, avatar_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        return templates.TemplateResponse(request, "avatars/not_found.html", status_code=404)
    tags = await _fetch_tags(db)
    avatar_tag_ids = await avatars_service.get_avatar_tag_ids(db, avatar_id)
    return templates.TemplateResponse(
        request,
        "avatars/detail.html",
        {"avatar": avatar, "tags": tags, "avatar_tag_ids": avatar_tag_ids, "avatar_id": avatar_id},
    )


@router.patch("/{avatar_id}/notes", response_class=HTMLResponse)
async def update_avatar_notes(
    request: Request, avatar_id: int, notes: str = Form(""), db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    avatar = await avatars_service.update_notes(db, avatar_id, notes)
    return templates.TemplateResponse(request, "avatars/_notes_form.html", {"avatar": avatar})


@router.post("/{avatar_id}/tags", response_class=HTMLResponse)
async def attach_tag(
    request: Request,
    avatar_id: int,
    tag_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    await avatars_service.add_tag_to_avatar(db, avatar_id, tag_id)
    tags = await _fetch_tags(db)
    avatar_tag_ids = await avatars_service.get_avatar_tag_ids(db, avatar_id)
    return templates.TemplateResponse(
        request,
        "avatars/_tag_assignment.html",
        {"tags": tags, "avatar_tag_ids": avatar_tag_ids, "avatar_id": avatar_id},
    )


@router.delete("/{avatar_id}/tags/{tag_id}", response_class=HTMLResponse)
async def detach_tag(
    request: Request, avatar_id: int, tag_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    await avatars_service.remove_tag_from_avatar(db, avatar_id, tag_id)
    tags = await _fetch_tags(db)
    avatar_tag_ids = await avatars_service.get_avatar_tag_ids(db, avatar_id)
    return templates.TemplateResponse(
        request,
        "avatars/_tag_assignment.html",
        {"tags": tags, "avatar_tag_ids": avatar_tag_ids, "avatar_id": avatar_id},
    )


@router.get("/tags/manage", response_class=HTMLResponse)
async def manage_tags_page(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    tags = await _fetch_tags(db)
    return templates.TemplateResponse(request, "avatars/tags.html", {"tags": tags})


@router.post("/tags", response_class=HTMLResponse)
async def create_tag(
    request: Request,
    name: str = Form(...),
    color: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    await avatars_service.create_tag(db, name, color or None)
    tags = await _fetch_tags(db)
    return templates.TemplateResponse(request, "avatars/_tags_list.html", {"tags": tags})


@router.delete("/tags/{tag_id}", response_class=HTMLResponse)
async def delete_tag(
    request: Request, tag_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    await avatars_service.delete_tag(db, tag_id)
    tags = await _fetch_tags(db)
    return templates.TemplateResponse(request, "avatars/_tags_list.html", {"tags": tags})


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
            "avatars/_sync_result.html",
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
        await vrchat_sync_service.full_avatars_sync(db, client)
    except VRChatAPIError as exc:
        return templates.TemplateResponse(
            request,
            "avatars/_sync_result.html",
            {"success": False, "message": f"同期に失敗しました: {exc}"},
        )
    finally:
        await client.close()

    return templates.TemplateResponse(
        request, "avatars/_sync_result.html", {"success": True, "message": "同期が完了しました。"}
    )
