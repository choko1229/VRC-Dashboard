"""アバター準備状況チェック。"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

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

_SORT_KEYS: dict[str, Callable[[Avatar], object]] = {
    "name": lambda a: a.name.lower(),
    "release_status": lambda a: a.release_status,
    "version": lambda a: a.version if a.version is not None else -1,
    "updated_at_vrchat": lambda a: a.updated_at_vrchat or a.last_synced_at,
    "created_at_vrchat": lambda a: a.created_at_vrchat or a.created_at,
}

_PLATFORM_COLUMNS: dict[str, InstrumentedAttribute[str | None]] = {
    "pc": Avatar.performance_rank,
    "android": Avatar.performance_rank_android,
    "ios": Avatar.performance_rank_ios,
}


def _parse_tag_id(raw: str | None) -> int | None:
    """クエリパラメータの空文字列（フィルター解除時の`<select>`値）をNoneとして扱う。"""
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def _fetch_avatars(
    db: AsyncSession,
    *,
    tag_id: int | None,
    release_status: str,
    platform: str,
    q: str | None,
    sort_by: str,
    sort_dir: str,
) -> list[Avatar]:
    query = select(Avatar)
    if tag_id is not None:
        query = query.join(AvatarTag, AvatarTag.avatar_id == Avatar.id).where(
            AvatarTag.tag_id == tag_id
        )
    if release_status in ("public", "private"):
        query = query.where(Avatar.release_status == release_status)
    platform_column = _PLATFORM_COLUMNS.get(platform)
    if platform_column is not None:
        query = query.where(platform_column.isnot(None))
    if q:
        query = query.where(Avatar.name.ilike(f"%{q}%"))
    result = await db.execute(query)
    avatars = list(result.scalars().unique().all())

    key_func = _SORT_KEYS.get(sort_by, _SORT_KEYS["name"])
    avatars.sort(key=key_func, reverse=(sort_dir == "desc"))  # type: ignore[arg-type]
    return avatars


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


async def _build_client(db: AsyncSession, cipher: SecretCipher) -> VRChatClient | None:
    cookies = await vrchat_session_service.get_decrypted_cookies(db, cipher)
    if cookies is None:
        return None
    auth_cookie, two_factor_cookie = cookies
    user_agent = await app_config_service.get_vrchat_user_agent(db)
    return VRChatClient(
        user_agent=user_agent, auth_cookie=auth_cookie, two_factor_cookie=two_factor_cookie
    )


@router.get("", response_class=HTMLResponse)
async def avatars_page(
    request: Request,
    tag_id: str | None = None,
    release_status: str = "all",
    platform: str = "all",
    q: str | None = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    parsed_tag_id = _parse_tag_id(tag_id)
    avatars = await _fetch_avatars(
        db,
        tag_id=parsed_tag_id,
        release_status=release_status,
        platform=platform,
        q=q,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    tags = await _fetch_tags(db)
    avatar_tags_map = await _fetch_avatar_tags_map(db, [a.id for a in avatars])
    return templates.TemplateResponse(
        request,
        "avatars/list.html",
        {
            "avatars": avatars,
            "tags": tags,
            "avatar_tags_map": avatar_tags_map,
            "selected_tag_id": parsed_tag_id,
            "release_status": release_status,
            "platform": platform,
            "q": q or "",
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        },
    )


@router.get("/partials/list", response_class=HTMLResponse)
async def avatars_list_partial(
    request: Request,
    tag_id: str | None = None,
    release_status: str = "all",
    platform: str = "all",
    q: str | None = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    parsed_tag_id = _parse_tag_id(tag_id)
    avatars = await _fetch_avatars(
        db,
        tag_id=parsed_tag_id,
        release_status=release_status,
        platform=platform,
        q=q,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    avatar_tags_map = await _fetch_avatar_tags_map(db, [a.id for a in avatars])
    return templates.TemplateResponse(
        request,
        "avatars/_table.html",
        {
            "avatars": avatars,
            "avatar_tags_map": avatar_tags_map,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "release_status": release_status,
            "platform": platform,
            "q": q or "",
            "selected_tag_id": parsed_tag_id,
        },
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


async def _render_row(
    request: Request, db: AsyncSession, avatar_id: int, *, error: str | None = None
) -> HTMLResponse:
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        return HTMLResponse("", status_code=404)
    tags_map = await _fetch_avatar_tags_map(db, [avatar_id])
    return templates.TemplateResponse(
        request,
        "avatars/_row.html",
        {"avatar": avatar, "avatar_tags_map": tags_map, "error": error},
    )


@router.post("/{avatar_id}/rename", response_class=HTMLResponse)
async def rename_avatar(
    request: Request,
    avatar_id: int,
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    """アバター名をVRChat側に反映する（実際のアバターデータを書き換える）。"""
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        return HTMLResponse("", status_code=404)
    name = name.strip()
    if not name:
        return await _render_row(request, db, avatar_id, error="名前を空にはできません。")

    client = await _build_client(db, cipher)
    if client is None:
        return await _render_row(request, db, avatar_id, error="VRChatと連携していません。")
    try:
        await client.update_avatar(avatar.vrchat_avatar_id, name=name)
    except VRChatAPIError as exc:
        logger.warning("アバター名の更新に失敗しました: %s", exc)
        return await _render_row(request, db, avatar_id, error=f"更新に失敗しました: {exc}")
    finally:
        await client.close()

    await avatars_service.update_avatar_fields(db, avatar_id, name=name)
    return await _render_row(request, db, avatar_id)


@router.post("/{avatar_id}/description", response_class=HTMLResponse)
async def update_avatar_description(
    request: Request,
    avatar_id: int,
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    """アバターの説明文をVRChat側に反映する（実際のアバターデータを書き換える）。"""
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        return HTMLResponse("", status_code=404)

    client = await _build_client(db, cipher)
    if client is None:
        return await _render_row(request, db, avatar_id, error="VRChatと連携していません。")
    try:
        await client.update_avatar(avatar.vrchat_avatar_id, description=description)
    except VRChatAPIError as exc:
        logger.warning("アバター説明の更新に失敗しました: %s", exc)
        return await _render_row(request, db, avatar_id, error=f"更新に失敗しました: {exc}")
    finally:
        await client.close()

    await avatars_service.update_avatar_fields(db, avatar_id, description=description)
    return await _render_row(request, db, avatar_id)


@router.post("/{avatar_id}/release-status", response_class=HTMLResponse)
async def update_avatar_release_status(
    request: Request,
    avatar_id: int,
    release_status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    """アバターの公開/非公開状態をVRChat側に反映する（実際のアバターデータを書き換える）。"""
    if release_status not in ("public", "private"):
        return HTMLResponse("", status_code=400)
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        return HTMLResponse("", status_code=404)

    client = await _build_client(db, cipher)
    if client is None:
        return await _render_row(request, db, avatar_id, error="VRChatと連携していません。")
    try:
        await client.update_avatar(avatar.vrchat_avatar_id, release_status=release_status)
    except VRChatAPIError as exc:
        logger.warning("アバター公開状態の更新に失敗しました: %s", exc)
        return await _render_row(request, db, avatar_id, error=f"更新に失敗しました: {exc}")
    finally:
        await client.close()

    await avatars_service.update_avatar_fields(db, avatar_id, release_status=release_status)
    return await _render_row(request, db, avatar_id)


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
