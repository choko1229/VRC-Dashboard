"""今日の予定（カレンダー表示・手動登録・VRChatカレンダー取込）。"""

from __future__ import annotations

import logging
from datetime import date, time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_cipher, get_current_user
from app.core.security import SecretCipher
from app.core.templating import templates
from app.db.session import get_db
from app.models.schedule_event import ScheduleEvent
from app.services import (
    app_config_service,
    calendar_view,
    schedule_service,
    vrchat_session_service,
    vrchat_sync_service,
)
from app.services.vrchat.client import VRChatAPIError, VRChatClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedule", dependencies=[Depends(get_current_user)])


@router.get("", response_class=HTMLResponse)
async def schedule_page(
    request: Request,
    year: int | None = None,
    month: int | None = None,
) -> HTMLResponse:
    today = date.today()
    year = year or today.year
    month = month or today.month
    return templates.TemplateResponse(
        request, "schedule/calendar.html", {"year": year, "month": month, "today": today}
    )


@router.get("/partials/month", response_class=HTMLResponse)
async def month_partial(
    request: Request, year: int, month: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    weeks = calendar_view.month_grid(year, month)
    start_date = weeks[0][0]
    end_date = weeks[-1][-1]
    events = await schedule_service.list_events_for_range(db, start_date, end_date)

    events_by_day: dict[date, list[ScheduleEvent]] = {}
    for event in events:
        events_by_day.setdefault(event.event_date, []).append(event)

    prev_year, prev_month = calendar_view.previous_month(year, month)
    next_year, next_month = calendar_view.next_month(year, month)

    return templates.TemplateResponse(
        request,
        "schedule/_month_grid.html",
        {
            "year": year,
            "month": month,
            "weeks": weeks,
            "events_by_day": events_by_day,
            "today": date.today(),
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )


@router.get("/partials/week", response_class=HTMLResponse)
async def week_partial(
    request: Request, start_date: date, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    days = calendar_view.week_days(start_date)
    events = await schedule_service.list_events_for_range(db, days[0], days[-1])

    events_by_day: dict[date, list[ScheduleEvent]] = {}
    for event in events:
        events_by_day.setdefault(event.event_date, []).append(event)

    return templates.TemplateResponse(
        request,
        "schedule/_week_grid.html",
        {"days": days, "events_by_day": events_by_day, "today": date.today()},
    )


@router.get("/partials/day/{event_date}", response_class=HTMLResponse)
async def day_partial(
    request: Request, event_date: date, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    events = await schedule_service.list_events_for_day(db, event_date)
    return templates.TemplateResponse(
        request, "schedule/_day_panel.html", {"event_date": event_date, "events": events}
    )


@router.get("/events/new", response_class=HTMLResponse)
async def new_event_form(
    request: Request, event_date: date, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "schedule/_event_form.html", {"event_date": event_date, "event": None}
    )


@router.post("/events", response_class=HTMLResponse)
async def create_event(
    request: Request,
    title: str = Form(...),
    event_date: date = Form(...),
    start_time: time | None = Form(None),
    world_id: str = Form(""),
    world_name: str = Form(""),
    memo: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    await schedule_service.create_event(
        db,
        title=title,
        event_date=event_date,
        start_time=start_time,
        world_id=world_id,
        world_name=world_name,
        avatar_id=None,
        memo=memo,
    )
    events = await schedule_service.list_events_for_day(db, event_date)
    return templates.TemplateResponse(
        request, "schedule/_day_panel.html", {"event_date": event_date, "events": events}
    )


@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
async def edit_event_form(
    request: Request, event_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    event = await db.get(ScheduleEvent, event_id)
    if event is None:
        return templates.TemplateResponse(request, "schedule/_not_found.html", status_code=404)
    return templates.TemplateResponse(
        request, "schedule/_event_form.html", {"event_date": event.event_date, "event": event}
    )


@router.patch("/events/{event_id}", response_class=HTMLResponse)
async def update_event(
    request: Request,
    event_id: int,
    title: str = Form(...),
    event_date: date = Form(...),
    start_time: time | None = Form(None),
    world_id: str = Form(""),
    world_name: str = Form(""),
    memo: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    await schedule_service.update_event(
        db,
        event_id,
        title=title,
        event_date=event_date,
        start_time=start_time,
        world_id=world_id,
        world_name=world_name,
        avatar_id=None,
        memo=memo,
    )
    events = await schedule_service.list_events_for_day(db, event_date)
    return templates.TemplateResponse(
        request, "schedule/_day_panel.html", {"event_date": event_date, "events": events}
    )


@router.delete("/events/{event_id}", response_class=HTMLResponse)
async def delete_event(
    request: Request, event_id: int, event_date: date, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    await schedule_service.delete_event(db, event_id)
    events = await schedule_service.list_events_for_day(db, event_date)
    return templates.TemplateResponse(
        request, "schedule/_day_panel.html", {"event_date": event_date, "events": events}
    )


@router.post("/import/vrchat-calendar", response_class=HTMLResponse)
async def import_vrchat_calendar(
    request: Request,
    vrchat_group_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    cookies = await vrchat_session_service.get_decrypted_cookies(db, cipher)
    if cookies is None:
        return templates.TemplateResponse(
            request,
            "schedule/_import_result.html",
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
        imported = await vrchat_sync_service.import_group_calendar(db, client, vrchat_group_id)
    except VRChatAPIError as exc:
        return templates.TemplateResponse(
            request,
            "schedule/_import_result.html",
            {"success": False, "message": f"取込に失敗しました: {exc}"},
        )
    finally:
        await client.close()

    return templates.TemplateResponse(
        request,
        "schedule/_import_result.html",
        {"success": True, "message": f"{imported}件の新規予定を取り込みました。"},
    )
