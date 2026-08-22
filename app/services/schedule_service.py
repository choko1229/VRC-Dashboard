"""今日の予定のCRUDとVRChatカレンダー取込。"""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule_event import ScheduleEvent
from app.schemas.vrchat import VRChatCalendarEvent


async def list_events_for_range(
    db: AsyncSession, start_date: date, end_date: date
) -> list[ScheduleEvent]:
    result = await db.execute(
        select(ScheduleEvent)
        .where(ScheduleEvent.event_date >= start_date, ScheduleEvent.event_date <= end_date)
        .order_by(ScheduleEvent.event_date, ScheduleEvent.start_time)
    )
    return list(result.scalars().all())


async def list_events_for_day(db: AsyncSession, event_date: date) -> list[ScheduleEvent]:
    result = await db.execute(
        select(ScheduleEvent)
        .where(ScheduleEvent.event_date == event_date)
        .order_by(ScheduleEvent.start_time)
    )
    return list(result.scalars().all())


async def create_event(
    db: AsyncSession,
    *,
    title: str,
    event_date: date,
    start_time: time | None,
    world_id: str | None,
    world_name: str | None,
    avatar_id: int | None,
    memo: str | None,
) -> ScheduleEvent:
    event = ScheduleEvent(
        title=title,
        event_date=event_date,
        start_time=start_time,
        world_id=world_id or None,
        world_name=world_name or None,
        avatar_id=avatar_id,
        memo=memo or None,
        source="manual",
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def update_event(
    db: AsyncSession,
    event_id: int,
    *,
    title: str,
    event_date: date,
    start_time: time | None,
    world_id: str | None,
    world_name: str | None,
    avatar_id: int | None,
    memo: str | None,
) -> ScheduleEvent | None:
    event = await db.get(ScheduleEvent, event_id)
    if event is None:
        return None
    event.title = title
    event.event_date = event_date
    event.start_time = start_time
    event.world_id = world_id or None
    event.world_name = world_name or None
    event.avatar_id = avatar_id
    event.memo = memo or None
    await db.commit()
    return event


async def delete_event(db: AsyncSession, event_id: int) -> None:
    event = await db.get(ScheduleEvent, event_id)
    if event is not None:
        await db.delete(event)
        await db.commit()


async def import_calendar_events(
    db: AsyncSession, calendar_events: list[VRChatCalendarEvent]
) -> int:
    """VRChatカレンダーイベントをvrchat_event_idでupsertする。戻り値は新規取込件数。"""
    imported = 0
    for calendar_event in calendar_events:
        result = await db.execute(
            select(ScheduleEvent).where(ScheduleEvent.vrchat_event_id == calendar_event.id)
        )
        row = result.scalar_one_or_none()
        event_date = calendar_event.starts_at.date() if calendar_event.starts_at else date.today()
        start_time = calendar_event.starts_at.time() if calendar_event.starts_at else None

        if row is None:
            db.add(
                ScheduleEvent(
                    title=calendar_event.title,
                    event_date=event_date,
                    start_time=start_time,
                    world_id=calendar_event.world_id,
                    memo=calendar_event.description,
                    source="vrchat_calendar",
                    vrchat_event_id=calendar_event.id,
                )
            )
            imported += 1
        else:
            row.title = calendar_event.title
            row.event_date = event_date
            row.start_time = start_time
            row.world_id = calendar_event.world_id
            row.memo = calendar_event.description

    await db.commit()
    return imported
