"""フレンド個別の通知ON/OFF設定。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FriendNotificationPref(Base):
    __tablename__ = "friend_notification_pref"

    friend_id: Mapped[int] = mapped_column(
        ForeignKey("friend.id", ondelete="CASCADE"), primary_key=True
    )
    notify_on_online: Mapped[bool] = mapped_column(default=False)
    notify_on_offline: Mapped[bool] = mapped_column(default=False)
    notify_on_world_change: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
