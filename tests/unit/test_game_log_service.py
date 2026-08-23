"""ゲームログ取り込み・集計ロジックのユニットテスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.game_log_event import GameLogEvent
from app.models.game_log_instance import GameLogInstance
from app.schemas.game_log import GameLogEventIn
from app.services import game_log_service


def _dt(minute: int) -> datetime:
    return datetime(2026, 8, 17, 0, minute, 0, tzinfo=UTC)


def _aware(value: datetime) -> datetime:
    """SQLiteはDateTime(timezone=True)でもtzinfo無しで返すため、比較用にUTCを補う。"""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def test_instance_join_creates_instance(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await game_log_service.ingest_events(
            db,
            [
                GameLogEventIn(
                    event_type="instance_join",
                    occurred_at=_dt(0),
                    location="wrld_a:1",
                    world_id="wrld_a",
                    world_name="World A",
                )
            ],
        )

        instances = (await db.execute(select(GameLogInstance))).scalars().all()
        assert len(instances) == 1
        assert instances[0].world_name == "World A"
        assert instances[0].left_at is None


async def test_instance_leave_closes_open_instance(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await game_log_service.ingest_events(
            db,
            [
                GameLogEventIn(
                    event_type="instance_join", occurred_at=_dt(0), location="wrld_a:1"
                ),
                GameLogEventIn(event_type="instance_leave", occurred_at=_dt(15)),
            ],
        )

        instance = (await db.execute(select(GameLogInstance))).scalars().one()
        assert instance.left_at is not None
        assert _aware(instance.left_at) == _dt(15)


async def test_second_instance_join_closes_previous_without_explicit_leave(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await game_log_service.ingest_events(
            db,
            [
                GameLogEventIn(
                    event_type="instance_join", occurred_at=_dt(0), location="wrld_a:1"
                ),
                GameLogEventIn(
                    event_type="instance_join", occurred_at=_dt(20), location="wrld_b:1"
                ),
            ],
        )

        instances = (
            (await db.execute(select(GameLogInstance).order_by(GameLogInstance.joined_at)))
            .scalars()
            .all()
        )
        assert len(instances) == 2
        assert instances[0].left_at is not None
        assert _aware(instances[0].left_at) == _dt(20)
        assert instances[1].left_at is None


async def test_activity_events_attach_to_open_instance(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await game_log_service.ingest_events(
            db,
            [
                GameLogEventIn(
                    event_type="instance_join", occurred_at=_dt(0), location="wrld_a:1"
                ),
                GameLogEventIn(
                    event_type="player_join", occurred_at=_dt(1), player_name="Alice"
                ),
                GameLogEventIn(
                    event_type="video_play",
                    occurred_at=_dt(2),
                    detail="https://example.com/v",
                ),
                GameLogEventIn(
                    event_type="player_leave", occurred_at=_dt(3), player_name="Alice"
                ),
            ],
        )

        instance = (await db.execute(select(GameLogInstance))).scalars().one()
        events = (
            (
                await db.execute(
                    select(GameLogEvent)
                    .where(GameLogEvent.instance_id == instance.id)
                    .order_by(GameLogEvent.occurred_at)
                )
            )
            .scalars()
            .all()
        )
        assert [e.event_type for e in events] == ["player_join", "video_play", "player_leave"]


async def test_activity_event_without_open_instance_is_dropped(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await game_log_service.ingest_events(
            db, [GameLogEventIn(event_type="player_join", occurred_at=_dt(0), player_name="X")]
        )

        events = (await db.execute(select(GameLogEvent))).scalars().all()
        assert events == []


async def test_get_instance_summaries_counts_and_pagination(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        events = [
            GameLogEventIn(event_type="instance_join", occurred_at=_dt(0), location="wrld_a:1"),
            GameLogEventIn(event_type="player_join", occurred_at=_dt(1), player_name="A"),
            GameLogEventIn(event_type="player_join", occurred_at=_dt(2), player_name="B"),
            GameLogEventIn(event_type="player_leave", occurred_at=_dt(3), player_name="A"),
            GameLogEventIn(event_type="video_play", occurred_at=_dt(4), detail="https://x"),
            GameLogEventIn(event_type="instance_leave", occurred_at=_dt(15)),
        ]
        await game_log_service.ingest_events(db, events)

        summaries, has_more = await game_log_service.get_instance_summaries(db, page=0)
        assert has_more is False
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.join_count == 2
        assert summary.leave_count == 1
        assert summary.video_count == 1
        assert summary.duration_label == "15分"


async def test_get_instance_events_orders_newest_first(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await game_log_service.ingest_events(
            db,
            [
                GameLogEventIn(
                    event_type="instance_join", occurred_at=_dt(0), location="wrld_a:1"
                ),
                GameLogEventIn(
                    event_type="player_join", occurred_at=_dt(1), player_name="First"
                ),
                GameLogEventIn(
                    event_type="player_join", occurred_at=_dt(2), player_name="Second"
                ),
            ],
        )
        instance = (await db.execute(select(GameLogInstance))).scalars().one()

        events = await game_log_service.get_instance_events(db, instance.id)
        assert [e.player_name for e in events] == ["Second", "First"]
