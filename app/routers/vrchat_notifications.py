"""VRChat自体の通知ログ（招待/フレンドリクエスト/グループイベント等）の一覧・アクション。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_cipher, get_current_vrchat_user
from app.core.security import SecretCipher
from app.core.templating import templates
from app.db.session import get_db
from app.models.dashboard_user import DashboardUser
from app.services import vrchat_notification_service, vrchat_session_service

router = APIRouter(prefix="/notifications", dependencies=[Depends(get_current_vrchat_user)])


async def _content_context(
    db: AsyncSession, user_id: int, *, notification_type: str, q: str, sort_dir: str
) -> dict[str, object]:
    entries, has_more = await vrchat_notification_service.get_notifications(
        db,
        user_id,
        page=0,
        notification_type=notification_type or None,
        q=q,
        sort_dir=sort_dir,
    )
    return {
        "entries": entries,
        "has_more": has_more,
        "next_page": 1,
        "notification_type": notification_type,
        "search": q,
        "sort_dir": sort_dir,
        "type_choices": vrchat_notification_service.known_type_choices(),
    }


@router.get("", response_class=HTMLResponse)
async def notifications_page(
    request: Request,
    notification_type: str = "",
    q: str = "",
    sort_dir: str = "desc",
    db: AsyncSession = Depends(get_db),
    user: DashboardUser = Depends(get_current_vrchat_user),
) -> HTMLResponse:
    context = await _content_context(
        db, user.id, notification_type=notification_type, q=q, sort_dir=sort_dir
    )
    return templates.TemplateResponse(request, "notifications/list.html", context)


@router.get("/content", response_class=HTMLResponse)
async def notifications_content(
    request: Request,
    notification_type: str = "",
    q: str = "",
    sort_dir: str = "desc",
    db: AsyncSession = Depends(get_db),
    user: DashboardUser = Depends(get_current_vrchat_user),
) -> HTMLResponse:
    context = await _content_context(
        db, user.id, notification_type=notification_type, q=q, sort_dir=sort_dir
    )
    return templates.TemplateResponse(request, "notifications/_content.html", context)


@router.get("/rows", response_class=HTMLResponse)
async def notifications_rows(
    request: Request,
    notification_type: str = "",
    q: str = "",
    sort_dir: str = "desc",
    page: int = 0,
    db: AsyncSession = Depends(get_db),
    user: DashboardUser = Depends(get_current_vrchat_user),
) -> HTMLResponse:
    entries, has_more = await vrchat_notification_service.get_notifications(
        db,
        user.id,
        page=page,
        notification_type=notification_type or None,
        q=q,
        sort_dir=sort_dir,
    )
    return templates.TemplateResponse(
        request,
        "notifications/_rows.html",
        {
            "entries": entries,
            "has_more": has_more,
            "next_page": page + 1,
            "notification_type": notification_type,
            "search": q,
            "sort_dir": sort_dir,
        },
    )


@router.post("/{notification_id}/accept", response_class=HTMLResponse)
async def accept_notification(
    request: Request,
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
    user: DashboardUser = Depends(get_current_vrchat_user),
) -> HTMLResponse:
    row = await vrchat_notification_service.get_notification(db, user.id, notification_id)
    if row is None:
        return HTMLResponse("", status_code=404)
    client = await vrchat_session_service.build_client(db, cipher, user.id)
    try:
        await vrchat_notification_service.accept(db, client, row)
    finally:
        if client is not None:
            await client.close()
    return templates.TemplateResponse(
        request, "notifications/_row.html", {"entry": row, "sort_dir": "desc"}
    )


@router.post("/{notification_id}/decline", response_class=HTMLResponse)
async def decline_notification(
    request: Request,
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
    user: DashboardUser = Depends(get_current_vrchat_user),
) -> HTMLResponse:
    row = await vrchat_notification_service.get_notification(db, user.id, notification_id)
    if row is None:
        return HTMLResponse("", status_code=404)
    client = await vrchat_session_service.build_client(db, cipher, user.id)
    try:
        await vrchat_notification_service.decline(db, client, row)
    finally:
        if client is not None:
            await client.close()
    return HTMLResponse("")


@router.delete("/{notification_id}", response_class=HTMLResponse)
async def delete_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
    user: DashboardUser = Depends(get_current_vrchat_user),
) -> HTMLResponse:
    row = await vrchat_notification_service.get_notification(db, user.id, notification_id)
    if row is None:
        return HTMLResponse("", status_code=404)
    client = await vrchat_session_service.build_client(db, cipher, user.id)
    try:
        await vrchat_notification_service.decline(db, client, row)
    finally:
        if client is not None:
            await client.close()
    return HTMLResponse("")
