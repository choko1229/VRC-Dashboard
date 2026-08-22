"""今日の予定（手動登録・VRChatカレンダー取込の両方に対応）。"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, ForeignKey, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScheduleEvent(Base):
    __tablename__ = "schedule_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    event_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time | None] = mapped_column(Time, default=None)
    world_id: Mapped[str | None] = mapped_column(String(100), default=None)
    world_name: Mapped[str | None] = mapped_column(String(255), default=None)
    avatar_id: Mapped[int | None] = mapped_column(
        ForeignKey("avatar.id", ondelete="SET NULL"), default=None
    )
    memo: Mapped[str | None] = mapped_column(default=None)
    # "manual" / "vrchat_calendar"
    source: Mapped[str] = mapped_column(String(20), default="manual")
    vrchat_event_id: Mapped[str | None] = mapped_column(String(100), unique=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
