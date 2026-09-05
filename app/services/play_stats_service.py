"""自分自身のプレイ記録（いつ・どのぐらい・どんなワールドで・だれと）の集計。

VRChat公式APIには自分自身の過去の滞在履歴が存在しないため、デスクトップエージェントが
収集したゲームログ（game_log_instance/game_log_event、app.services.game_log_service参照）
のみが情報源。エージェントが稼働していた期間のログしか無いため、あくまでこのダッシュボードが
観測できた範囲の集計になる（フレンドのアクティビティヒートマップと同じ制約、
friends_service.compute_activity_statsのコメント参照）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.friend import Friend
from app.models.game_log_instance import GameLogInstance
from app.services import game_log_agent_token_service, game_log_service

_JST = ZoneInfo("Asia/Tokyo")
_WEEKDAY_LABELS_JA = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _duration_minutes(instance: GameLogInstance, *, now: datetime) -> float:
    end = _aware(instance.left_at) if instance.left_at is not None else now
    return max(0.0, (end - _aware(instance.joined_at)).total_seconds() / 60)


@dataclass
class HeatmapStats:
    grid: list[list[int]]  # grid[曜日(0=月...6=日)][時(0-23)] = 訪問開始回数
    max_count: int
    total_visits: int
    most_active_weekday: str | None
    peak_hour_range: str | None


@dataclass
class DailyPlayEntry:
    day: date
    minutes: float


@dataclass
class WorldStats:
    world_id: str | None
    world_name: str
    visit_count: int
    total_minutes: float


@dataclass
class FriendTogetherStats:
    friend: Friend
    join_count: int
    together_minutes: float


@dataclass
class PlayStatsSummary:
    total_visits: int
    total_minutes: float
    distinct_world_count: int
    distinct_friend_count: int


async def _get_all_instances(db: AsyncSession) -> list[GameLogInstance]:
    result = await db.execute(select(GameLogInstance).order_by(GameLogInstance.joined_at))
    return list(result.scalars().all())


def get_summary(
    instances: list[GameLogInstance], friend_count: int, *, now: datetime | None = None
) -> PlayStatsSummary:
    now = now or datetime.now(UTC)
    total_minutes = sum(_duration_minutes(i, now=now) for i in instances)
    distinct_worlds = {i.world_id or i.location for i in instances}
    return PlayStatsSummary(
        total_visits=len(instances),
        total_minutes=total_minutes,
        distinct_world_count=len(distinct_worlds),
        distinct_friend_count=friend_count,
    )


def get_weekday_hour_heatmap(instances: list[GameLogInstance]) -> HeatmapStats:
    """訪問開始時刻（JST基準）を曜日×時間帯に集計する。

    friends_service.compute_activity_statsと同じ考え方（滞在時間の重み付けはせず、
    「その時間帯に訪問を開始した回数」を数える簡易な集計）。
    """
    grid = [[0] * 24 for _ in range(7)]
    for instance in instances:
        local = _aware(instance.joined_at).astimezone(_JST)
        grid[local.weekday()][local.hour] += 1

    total_visits = len(instances)
    if total_visits == 0:
        return HeatmapStats(
            grid=grid, max_count=0, total_visits=0, most_active_weekday=None, peak_hour_range=None
        )

    weekday_totals = [sum(row) for row in grid]
    most_active_weekday = _WEEKDAY_LABELS_JA[weekday_totals.index(max(weekday_totals))]

    hour_totals = [sum(grid[w][h] for w in range(7)) for h in range(24)]
    peak_hour = hour_totals.index(max(hour_totals))
    peak_hour_range = f"{peak_hour:02d}:00-{(peak_hour + 1) % 24:02d}:00"

    return HeatmapStats(
        grid=grid,
        max_count=max(max(row) for row in grid),
        total_visits=total_visits,
        most_active_weekday=most_active_weekday,
        peak_hour_range=peak_hour_range,
    )


def get_daily_play_minutes(
    instances: list[GameLogInstance], *, days: int = 30, now: datetime | None = None
) -> list[DailyPlayEntry]:
    """直近days日分（JST基準の暦日）の合計プレイ時間を日別に集計する。

    日をまたぐ滞在は、開始日（JST）に丸ごと計上する簡易な近似。
    """
    now = now or datetime.now(UTC)
    now_jst_date = now.astimezone(_JST).date()
    start_date = now_jst_date - timedelta(days=days - 1)

    totals: dict[date, float] = {}
    for instance in instances:
        local_date = _aware(instance.joined_at).astimezone(_JST).date()
        if local_date < start_date or local_date > now_jst_date:
            continue
        totals[local_date] = totals.get(local_date, 0.0) + _duration_minutes(instance, now=now)

    entries = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        entries.append(DailyPlayEntry(day=day, minutes=totals.get(day, 0.0)))
    return entries


def get_top_worlds(
    instances: list[GameLogInstance], *, limit: int = 10, now: datetime | None = None
) -> list[WorldStats]:
    now = now or datetime.now(UTC)
    grouped: dict[str, WorldStats] = {}
    for instance in instances:
        key = instance.world_id or instance.location
        stats = grouped.setdefault(
            key,
            WorldStats(
                world_id=instance.world_id,
                world_name=instance.world_name or "不明なワールド",
                visit_count=0,
                total_minutes=0.0,
            ),
        )
        stats.visit_count += 1
        stats.total_minutes += _duration_minutes(instance, now=now)

    return sorted(grouped.values(), key=lambda s: s.total_minutes, reverse=True)[:limit]


async def get_all_friends_together(db: AsyncSession) -> list[FriendTogetherStats]:
    """一緒に居たことがある全フレンドを、一緒に居た時間の多い順に返す（件数制限無し）。"""
    friends = list((await db.execute(select(Friend))).scalars().all())
    co_presence = await game_log_service.get_friend_co_presence_stats(
        db, [f.vrchat_user_id for f in friends]
    )
    ranked = [
        FriendTogetherStats(
            friend=friend,
            join_count=co_presence[friend.vrchat_user_id].join_count,
            together_minutes=co_presence[friend.vrchat_user_id].together_seconds / 60,
        )
        for friend in friends
        if friend.vrchat_user_id in co_presence
    ]
    ranked.sort(key=lambda s: s.together_minutes, reverse=True)
    return ranked


@dataclass
class PlayStatsPage:
    summary: PlayStatsSummary
    heatmap: HeatmapStats
    daily: list[DailyPlayEntry]
    top_worlds: list[WorldStats]
    top_friends: list[FriendTogetherStats]


async def get_play_stats_page(
    db: AsyncSession, *, daily_days: int = 30, top_friends_limit: int = 10
) -> PlayStatsPage:
    instances = await _get_all_instances(db)
    all_friends_together = await get_all_friends_together(db)
    now = await game_log_agent_token_service.get_effective_now(db)
    summary = get_summary(instances, len(all_friends_together), now=now)
    return PlayStatsPage(
        summary=summary,
        heatmap=get_weekday_hour_heatmap(instances),
        daily=get_daily_play_minutes(instances, days=daily_days, now=now),
        top_worlds=get_top_worlds(instances, now=now),
        top_friends=all_friends_together[:top_friends_limit],
    )
