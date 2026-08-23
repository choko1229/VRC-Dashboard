"""自分自身のプレイ記録（いつ・どのぐらい・どんなワールドで・だれと）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.templating import templates
from app.db.session import get_db
from app.services import play_stats_service

router = APIRouter(prefix="/stats", dependencies=[Depends(get_current_user)])


@router.get("", response_class=HTMLResponse)
async def play_stats_page(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    page = await play_stats_service.get_play_stats_page(db)
    return templates.TemplateResponse(request, "stats/page.html", {"page": page})
