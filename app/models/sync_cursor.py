"""REST同期の最終実行状況。UIの「最終同期: n分前」表示と、連打防止に使う。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncCursor(Base):
    __tablename__ = "sync_cursor"

    # "avatars" / "vrchat_calendar" / "friends_bootstrap" 等
    resource_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_success: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
