"""自分自身のプレイ記録集計（play_stats_service）のユニットテスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.friend import Friend
from app.models.game_log_event import GameLogEvent
from app.models.game_log_instance import GameLogInstance
from app.services import play_stats_service


def _dt(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_get_summary_empty() -> None:
    summary = play_stats_service.get_summary([], 0)
    assert summary.total_visits == 0
    assert summary.total_minutes == 0
    assert summary.distinct_world_count == 0


def test_get_summary_counts_distinct_worlds_and_minutes() -> None:
    instances = [
        GameLogInstance(
            location="wrld_a:1",
            world_id="wrld_a",
            joined_at=_dt(2026, 8, 1, 0, 0),
            left_at=_dt(2026, 8, 1, 1, 0),
        ),
        GameLogInstance(
            location="wrld_a:2",
            world_id="wrld_a",
            joined_at=_dt(2026, 8, 2, 0, 0),
            left_at=_dt(2026, 8, 2, 0, 30),
        ),
        GameLogInstance(
            location="wrld_b:1",
            world_id="wrld_b",
            joined_at=_dt(2026, 8, 3, 0, 0),
            left_at=_dt(2026, 8, 3, 2, 0),
        ),
    ]
    summary = play_stats_service.get_summary(instances, 5)
    assert summary.total_visits == 3
    assert summary.total_minutes == 60 + 30 + 120
    assert summary.distinct_world_count == 2
    assert summary.distinct_friend_count == 5


def test_get_weekday_hour_heatmap_buckets_by_jst_weekday_and_hour() -> None:
    # UTC 2026-08-23(日) 15:00 -> JST 2026-08-24(月) 00:00
    instances = [
        GameLogInstance(location="wrld_a:1", joined_at=_dt(2026, 8, 23, 15, 0), left_at=None),
    ]
    heatmap = play_stats_service.get_weekday_hour_heatmap(instances)
    assert heatmap.total_visits == 1
    assert heatmap.grid[0][0] == 1  # 月曜日(index 0) 0時
    assert heatmap.most_active_weekday == "月曜日"
    assert heatmap.peak_hour_range == "00:00-01:00"


def test_get_weekday_hour_heatmap_empty() -> None:
    heatmap = play_stats_service.get_weekday_hour_heatmap([])
    assert heatmap.total_visits == 0
    assert heatmap.most_active_weekday is None


def test_get_daily_play_minutes_attributes_to_start_day_jst() -> None:
    now = datetime.now(UTC)
    today_jst = now.astimezone(play_stats_service._JST).date()
    instances = [
        GameLogInstance(
            location="wrld_a:1",
            joined_at=now.replace(hour=0, minute=0, second=0, microsecond=0),
            left_at=now,
        ),
    ]
    daily = play_stats_service.get_daily_play_minutes(instances, days=7)
    assert len(daily) == 7
    assert daily[-1].day == today_jst
    assert daily[-1].minutes >= 0


def test_get_daily_play_minutes_excludes_out_of_range_visits() -> None:
    instances = [
        GameLogInstance(
            location="wrld_a:1",
            joined_at=_dt(2000, 1, 1, 0, 0),
            left_at=_dt(2000, 1, 1, 1, 0),
        ),
    ]
    daily = play_stats_service.get_daily_play_minutes(instances, days=7)
    assert all(entry.minutes == 0 for entry in daily)


def test_get_top_worlds_sorts_by_total_minutes() -> None:
    instances = [
        GameLogInstance(
            location="wrld_a:1", world_id="wrld_a", world_name="World A",
            joined_at=_dt(2026, 8, 1, 0, 0), left_at=_dt(2026, 8, 1, 0, 30),
        ),
        GameLogInstance(
            location="wrld_b:1", world_id="wrld_b", world_name="World B",
            joined_at=_dt(2026, 8, 2, 0, 0), left_at=_dt(2026, 8, 2, 2, 0),
        ),
    ]
    top_worlds = play_stats_service.get_top_worlds(instances)
    assert [w.world_name for w in top_worlds] == ["World B", "World A"]
    assert top_worlds[0].visit_count == 1


async def test_get_all_friends_together_uses_game_log_co_presence(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        db.add(Friend(vrchat_user_id="usr_a", display_name="A"))
        db.add(Friend(vrchat_user_id="usr_b", display_name="B"))
        await db.commit()

        instance = GameLogInstance(
            location="wrld_a:1", joined_at=_dt(2026, 8, 1, 0, 0), left_at=_dt(2026, 8, 1, 1, 0)
        )
        db.add(instance)
        await db.flush()
        db.add(
            GameLogEvent(
                instance_id=instance.id,
                event_type="player_join",
                occurred_at=_dt(2026, 8, 1, 0, 10),
                player_vrchat_user_id="usr_a",
            )
        )
        await db.commit()

        results = await play_stats_service.get_all_friends_together(db)

        assert [r.friend.vrchat_user_id for r in results] == ["usr_a"]
        assert results[0].join_count == 1


async def test_get_play_stats_page_returns_empty_state_without_error(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        page = await play_stats_service.get_play_stats_page(db)
        assert page.summary.total_visits == 0
        assert page.daily
        assert page.top_worlds == []
        assert page.top_friends == []
