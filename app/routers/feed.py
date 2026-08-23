"""全フレンド横断のアクティビティフィード。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.templating import templates
from app.db.session import get_db
from app.services import feed_service

router = APIRouter(prefix="/feed", dependencies=[Depends(get_current_user)])


async def _content_context(
    db: AsyncSession, *, event_type: str, favorites_only: bool, q: str
) -> dict[str, object]:
    entries, has_more = await feed_service.get_feed_entries(
        db,
        page=0,
        event_type=None if event_type == "all" else event_type,
        favorites_only=favorites_only,
        search=q,
    )
    return {
        "entries": entries,
        "has_more": has_more,
        "next_page": 1,
        "event_type": event_type,
        "favorites_only": favorites_only,
        "search": q,
    }


@router.get("", response_class=HTMLResponse)
async def feed_page(
    request: Request,
    event_type: str = "all",
    favorites_only: bool = False,
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    context = await _content_context(
        db, event_type=event_type, favorites_only=favorites_only, q=q
    )
    return templates.TemplateResponse(request, "feed/list.html", context)


@router.get("/content", response_class=HTMLResponse)
async def feed_content(
    request: Request,
    event_type: str = "all",
    favorites_only: bool = False,
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """フィルター/お気に入り/検索の変更時に、フィルターバーごと再描画する（アクティブなタブの
    見た目を正しく更新するため。テーブル本体だけ差し替えるとタブのハイライトがずれる）。
    """
    context = await _content_context(
        db, event_type=event_type, favorites_only=favorites_only, q=q
    )
    return templates.TemplateResponse(request, "feed/_content.html", context)


@router.get("/rows", response_class=HTMLResponse)
async def feed_rows(
    request: Request,
    event_type: str = "all",
    favorites_only: bool = False,
    q: str = "",
    page: int = 0,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """「もっと見る」専用。フィルターバーは再描画せず行だけ追加する。"""
    entries, has_more = await feed_service.get_feed_entries(
        db,
        page=page,
        event_type=None if event_type == "all" else event_type,
        favorites_only=favorites_only,
        search=q,
    )
    return templates.TemplateResponse(
        request,
        "feed/_rows.html",
        {
            "entries": entries,
            "has_more": has_more,
            "next_page": page + 1,
            "event_type": event_type,
            "favorites_only": favorites_only,
            "search": q,
        },
    )
