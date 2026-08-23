"""インスタンス滞在中に観測されたイベント（プレイヤー参加/退出・動画再生）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GameLogEvent(Base):
    __tablename__ = "game_log_event"
    __table_args__ = (
        Index("ix_game_log_event_instance_time", "instance_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(
        ForeignKey("game_log_instance.id", ondelete="CASCADE")
    )
    # player_join / player_leave / video_play
    event_type: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    player_name: Mapped[str | None] = mapped_column(String(100), default=None)
    player_vrchat_user_id: Mapped[str | None] = mapped_column(String(64), default=None)
    # video_playの場合のみ使用（再生されたURL）。
    detail: Mapped[str | None] = mapped_column(String(500), default=None)
