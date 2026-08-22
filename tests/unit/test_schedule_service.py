"""フェーズ4: 予定のCRUD・VRChatカレンダー取込のユニットテスト。"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.vrchat import VRChatCalendarEvent
from app.services import schedule_service


async def test_create_event_requires_only_title_and_date(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        event = await schedule_service.create_event(
            db,
            title="友達と集合",
            event_date=date(2026, 8, 23),
            start_time=None,
            world_id=None,
            world_name=None,
            avatar_id=None,
            memo=None,
        )
        assert event.id is not None
        assert event.title == "友達と集合"
        assert event.start_time is None
        assert event.source == "manual"


async def test_list_events_for_day_and_range(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await schedule_service.create_event(
            db,
            title="朝のイベント",
            event_date=date(2026, 8, 23),
            start_time=time(9, 0),
            world_id=None,
            world_name=None,
            avatar_id=None,
            memo=None,
        )
        await schedule_service.create_event(
            db,
            title="翌日の予定",
            event_date=date(2026, 8, 24),
            start_time=None,
            world_id=None,
            world_name=None,
            avatar_id=None,
            memo=None,
        )

        day_events = await schedule_service.list_events_for_day(db, date(2026, 8, 23))
        assert [e.title for e in day_events] == ["朝のイベント"]

        range_events = await schedule_service.list_events_for_range(
            db, date(2026, 8, 23), date(2026, 8, 24)
        )
        assert len(range_events) == 2


async def test_update_and_delete_event(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        event = await schedule_service.create_event(
            db,
            title="元のタイトル",
            event_date=date(2026, 8, 23),
            start_time=None,
            world_id=None,
            world_name=None,
            avatar_id=None,
            memo=None,
        )
        updated = await schedule_service.update_event(
            db,
            event.id,
            title="更新後タイトル",
            event_date=date(2026, 8, 25),
            start_time=time(18, 30),
            world_id="wrld_1",
            world_name="World",
            avatar_id=None,
            memo="メモ",
        )
        assert updated is not None
        assert updated.title == "更新後タイトル"
        assert updated.event_date == date(2026, 8, 25)

        await schedule_service.delete_event(db, event.id)
        remaining = await schedule_service.list_events_for_day(db, date(2026, 8, 25))
        assert remaining == []


async def test_import_calendar_events_upserts_on_vrchat_event_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        events = [
            VRChatCalendarEvent(
                id="evt_1",
                title="VRChatイベント",
                starts_at=datetime(2026, 9, 1, 20, 0),
                worldId="wrld_x",
            )
        ]
        imported = await schedule_service.import_calendar_events(db, events)
        assert imported == 1

        # 同じvrchat_event_idで再取込しても重複作成されず、内容が更新される
        updated_events = [
            VRChatCalendarEvent(
                id="evt_1",
                title="タイトル変更",
                starts_at=datetime(2026, 9, 1, 21, 0),
                worldId="wrld_x",
            )
        ]
        imported_again = await schedule_service.import_calendar_events(db, updated_events)
        assert imported_again == 0

        day_events = await schedule_service.list_events_for_day(db, date(2026, 9, 1))
        assert len(day_events) == 1
        assert day_events[0].title == "タイトル変更"
        assert day_events[0].source == "vrchat_calendar"
