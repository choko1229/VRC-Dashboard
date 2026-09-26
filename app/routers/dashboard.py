"""ダッシュボードホーム。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_vrchat_user
from app.core.templating import templates
from app.db.session import get_db
from app.models.dashboard_user import DashboardUser
from app.services import avatars_service, schedule_service, sidebar_service, vrchat_session_service

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request, user: DashboardUser = Depends(get_current_vrchat_user)
) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard/home.html", {"user": user})


@router.get("/partials/friends-sidebar", response_class=HTMLResponse)
async def friends_sidebar(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
) -> HTMLResponse:
    """全ページ共通の右サイドバーに表示するオンラインフレンド一覧（partials/friends_sidebar.html）。

    「オンライン(インスタンス別)/アクティブ/オフライン」に区分して表示する
    （app.services.sidebar_service参照）。VRChatログイン画面自身にも表示されるポーリングのため、
    VRChat未ログインでもリダイレクトはせず（無限リダイレクトになるため）、案内だけを表示する。
    """
    if await vrchat_session_service.get_active_session(db, user.id) is None:
        return templates.TemplateResponse(
            request, "partials/_friends_sidebar_list.html", {"groups": None}
        )
    groups = await sidebar_service.get_friend_sidebar_groups(db, user.id)
    return templates.TemplateResponse(
        request, "partials/_friends_sidebar_list.html", {"groups": groups}
    )


@router.get("/partials/dashboard/avatar-summary", response_class=HTMLResponse)
async def avatar_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: DashboardUser = Depends(get_current_vrchat_user),
) -> HTMLResponse:
    total = await avatars_service.count_avatars(db, user.id)
    untagged = await avatars_service.count_untagged_avatars(db, user.id)
    return templates.TemplateResponse(
        request,
        "dashboard/_avatar_summary.html",
        {"total": total, "untagged": untagged},
    )


@router.get("/partials/dashboard/schedule-today", response_class=HTMLResponse)
async def schedule_today(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: DashboardUser = Depends(get_current_vrchat_user),
) -> HTMLResponse:
    events = await schedule_service.list_events_for_day(db, user.id, date.today())
    return templates.TemplateResponse(
        request, "dashboard/_schedule_today.html", {"events": events}
    )
