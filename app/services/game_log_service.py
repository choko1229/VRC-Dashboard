"""ローカルエージェント（desktop_agent/）が送信するゲームログの取り込み・表示用集計。

VRChat公式APIには「訪問したインスタンスの入退室履歴」「参加者の入退室」「動画再生URL」は
一切含まれていない（これらはVRChatクライアントがローカルに出力するログファイルにのみ存在する）。
そのためこの機能はサーバー側のPipeline/API監視とは別に、ユーザーのPC上で動くローカル
エージェントがログファイルを解析し、`POST /api/game-log/events`で送信してきたイベントを
取り込む方式で成立している（詳細はREADME・desktop_agent/README.md参照）。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game_log_event import GameLogEvent
from app.models.game_log_instance import GameLogInstance
from app.schemas.game_log import GameLogEventIn
from app.services import game_log_agent_token_service

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20


def _aware(value: datetime) -> datetime:
    """SQLiteから読み出したnaive datetimeをUTC awareとして扱う（書き込み時と同じUTCのため）。"""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass
class CoPresenceStats:
    join_count: int
    together_seconds: float


@dataclass
class _InstanceVisit:
    my_joined_at: datetime
    my_left_at: datetime | None
    friend_joins: list[datetime] = field(default_factory=list)
    friend_leaves: list[datetime] = field(default_factory=list)


async def get_friend_co_presence_stats(
    db: AsyncSession, vrchat_user_ids: list[str]
) -> dict[str, CoPresenceStats]:
    """フレンドごとの「一緒に居たインスタンス数」「一緒に居た合計時間」をゲームログから概算する。

    自分自身の滞在期間（game_log_instance.joined_at〜left_at）と、そのインスタンス内で
    観測された当該フレンドのplayer_join〜player_leaveの期間を突き合わせて重なりを計算する。
    デスクトップエージェントが稼働していた期間のログしか無いため、あくまで概算
    （複数回の再入室は、最初のjoinから最後のleaveまでを1回の滞在とみなして単純化している）。
    """
    if not vrchat_user_ids:
        return {}

    rows = (
        await db.execute(
            select(
                GameLogEvent.instance_id,
                GameLogEvent.player_vrchat_user_id,
                GameLogEvent.event_type,
                GameLogEvent.occurred_at,
                GameLogInstance.joined_at,
                GameLogInstance.left_at,
            )
            .join(GameLogInstance, GameLogEvent.instance_id == GameLogInstance.id)
            .where(
                GameLogEvent.player_vrchat_user_id.in_(vrchat_user_ids),
                GameLogEvent.event_type.in_(("player_join", "player_leave")),
            )
        )
    ).all()

    # (instance_id, user_id) -> 自分の滞在期間 + そのフレンドのjoin/leave時刻一覧
    visits: dict[tuple[int, str], _InstanceVisit] = {}
    for instance_id, user_id, event_type, occurred_at, my_joined_at, my_left_at in rows:
        key = (instance_id, user_id)
        visit = visits.setdefault(
            key, _InstanceVisit(my_joined_at=my_joined_at, my_left_at=my_left_at)
        )
        target = visit.friend_joins if event_type == "player_join" else visit.friend_leaves
        target.append(occurred_at)

    now = datetime.now(UTC)
    stats: dict[str, CoPresenceStats] = defaultdict(lambda: CoPresenceStats(0, 0.0))
    for (_instance_id, user_id), visit in visits.items():
        if not visit.friend_joins:
            continue

        my_end = _aware(visit.my_left_at or now)
        start = max(_aware(min(visit.friend_joins)), _aware(visit.my_joined_at))
        friend_end = _aware(max(visit.friend_leaves)) if visit.friend_leaves else my_end
        end = min(friend_end, my_end)

        stat = stats[user_id]
        stat.join_count += 1
        if end > start:
            stat.together_seconds += (end - start).total_seconds()

    return dict(stats)


@dataclass
class GameLogInstanceSummary:
    instance: GameLogInstance
    join_count: int
    leave_count: int
    video_count: int
    duration_label: str


async def _get_open_instance(db: AsyncSession) -> GameLogInstance | None:
    result = await db.execute(
        select(GameLogInstance)
        .where(GameLogInstance.left_at.is_(None))
        .order_by(GameLogInstance.joined_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def ingest_events(db: AsyncSession, events: list[GameLogEventIn]) -> None:
    """ローカルエージェントから送られてきたイベントを取り込む。

    「現在滞在中のインスタンス」はDB上に高々1件（left_atがNULLの行）だけ存在する想定で、
    instance_joinで前のインスタンスを閉じて新規行を作り、instance_leaveで閉じ、
    それ以外のイベントは現在開いているインスタンスに紐づける。
    受信順ではなくoccurred_at昇順で処理することで、バッチ送信時の順序ゆらぎに対応する。
    """
    current_instance = await _get_open_instance(db)

    for event in sorted(events, key=lambda e: e.occurred_at):
        if event.event_type == "instance_join":
            if not event.location:
                logger.warning("locationの無いinstance_joinイベントを無視しました")
                continue
            if current_instance is not None and current_instance.left_at is None:
                current_instance.left_at = event.occurred_at
            current_instance = GameLogInstance(
                location=event.location,
                world_id=event.world_id,
                world_name=event.world_name,
                joined_at=event.occurred_at,
            )
            db.add(current_instance)
            await db.flush()
        elif event.event_type == "instance_leave":
            if current_instance is not None and current_instance.left_at is None:
                current_instance.left_at = event.occurred_at
        else:
            if current_instance is None:
                logger.warning(
                    "滞在中のインスタンスが無いため%sイベントを無視しました", event.event_type
                )
                continue
            db.add(
                GameLogEvent(
                    instance_id=current_instance.id,
                    event_type=event.event_type,
                    occurred_at=event.occurred_at,
                    player_name=event.player_name,
                    player_vrchat_user_id=event.player_vrchat_user_id,
                    detail=event.detail,
                )
            )

    await db.commit()


def format_duration_seconds(total_seconds: float) -> str:
    total_minutes = max(0, int(total_seconds // 60))
    if total_minutes < 60:
        return f"{total_minutes}分"
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}時間{minutes}分" if minutes else f"{hours}時間"


def _format_duration(joined_at: datetime, left_at: datetime | None, *, now: datetime) -> str:
    end = left_at or now
    joined_aware = joined_at if joined_at.tzinfo is not None else joined_at.replace(tzinfo=UTC)
    end_aware = end if end.tzinfo is not None else end.replace(tzinfo=UTC)
    return format_duration_seconds((end_aware - joined_aware).total_seconds())


async def get_instance_summaries(
    db: AsyncSession, *, page: int = 0
) -> tuple[list[GameLogInstanceSummary], bool]:
    """インスタンス訪問履歴を新しい順にページ取得する。(結果, 次ページの有無) を返す。"""
    result = await db.execute(
        select(GameLogInstance)
        .order_by(GameLogInstance.joined_at.desc())
        .offset(page * _PAGE_SIZE)
        .limit(_PAGE_SIZE + 1)
    )
    instances = list(result.scalars().all())
    has_more = len(instances) > _PAGE_SIZE
    instances = instances[:_PAGE_SIZE]
    if not instances:
        return [], False

    instance_ids = [instance.id for instance in instances]
    counts_result = await db.execute(
        select(
            GameLogEvent.instance_id, GameLogEvent.event_type, func.count().label("count")
        )
        .where(GameLogEvent.instance_id.in_(instance_ids))
        .group_by(GameLogEvent.instance_id, GameLogEvent.event_type)
    )
    counts: dict[tuple[int, str], int] = {
        (instance_id, event_type): count
        for instance_id, event_type, count in counts_result.all()
    }

    now = await game_log_agent_token_service.get_effective_now(db)
    summaries = [
        GameLogInstanceSummary(
            instance=instance,
            join_count=counts.get((instance.id, "player_join"), 0),
            leave_count=counts.get((instance.id, "player_leave"), 0),
            video_count=counts.get((instance.id, "video_play"), 0),
            duration_label=_format_duration(instance.joined_at, instance.left_at, now=now),
        )
        for instance in instances
    ]
    return summaries, has_more


async def get_instance_events(db: AsyncSession, instance_id: int) -> list[GameLogEvent]:
    result = await db.execute(
        select(GameLogEvent)
        .where(GameLogEvent.instance_id == instance_id)
        .order_by(GameLogEvent.occurred_at.desc())
    )
    return list(result.scalars().all())
