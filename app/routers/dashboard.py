"""ダッシュボードホーム。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.templating import templates
from app.db.session import get_db
from app.models.avatar import Avatar
from app.models.dashboard_user import DashboardUser
from app.services import avatars_service, schedule_service, sidebar_service

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request, user: DashboardUser = Depends(get_current_user)
) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard/home.html", {"user": user})


@router.get("/partials/friends-sidebar", response_class=HTMLResponse)
async def friends_sidebar(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """全ページ共通の右サイドバーに表示するオンラインフレンド一覧（partials/friends_sidebar.html）。

    「オンライン(インスタンス別)/アクティブ/オフライン」に区分して表示する
    （app.services.sidebar_service参照）。
    """
    groups = await sidebar_service.get_friend_sidebar_groups(db)
    return templates.TemplateResponse(
        request, "partials/_friends_sidebar_list.html", {"groups": groups}
    )


@router.get("/partials/dashboard/avatar-summary", response_class=HTMLResponse)
async def avatar_summary(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    total = len((await db.execute(select(Avatar.id))).scalars().all())
    untagged = await avatars_service.count_untagged_avatars(db)
    return templates.TemplateResponse(
        request,
        "dashboard/_avatar_summary.html",
        {"total": total, "untagged": untagged},
    )


@router.get("/partials/dashboard/schedule-today", response_class=HTMLResponse)
async def schedule_today(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    events = await schedule_service.list_events_for_day(db, date.today())
    return templates.TemplateResponse(
        request, "dashboard/_schedule_today.html", {"events": events}
    )
