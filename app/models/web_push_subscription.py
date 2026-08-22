"""ブラウザのWeb Push購読情報。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WebPushSubscription(Base):
    __tablename__ = "web_push_subscription"

    id: Mapped[int] = mapped_column(primary_key=True)
    dashboard_user_id: Mapped[int] = mapped_column(
        ForeignKey("dashboard_user.id", ondelete="CASCADE")
    )
    endpoint: Mapped[str] = mapped_column(unique=True)
    p256dh_key: Mapped[str] = mapped_column()
    auth_key: Mapped[str] = mapped_column()
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
