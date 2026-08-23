"""フレンドのオンライン状態変化を記録する追記専用の時系列ログ（全件保持、ユーザー指定）。

ほぼ全てのクエリが「フレンドXの直近N件」または「フレンドXの期間絞り込み」であるため、
(friend_id, occurred_at)の複合インデックスが要。
プルーニングは現時点で実装しない（ユーザーの明示的な選択）が、
将来数百万行規模になった場合は見直しが必要になる可能性がある。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FriendPresenceEvent(Base):
    __tablename__ = "friend_presence_event"
    __table_args__ = (
        Index("ix_friend_presence_event_friend_time", "friend_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    friend_id: Mapped[int] = mapped_column(ForeignKey("friend.id", ondelete="CASCADE"))
    # online / offline / location_change / status_change / avatar_change
    event_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str | None] = mapped_column(String(20), default=None)
    # status_changeイベントのみ使用（変化前のstatus。フィードでの「busy→active」等の表示に使う）。
    previous_status: Mapped[str | None] = mapped_column(String(20), default=None)
    world_id: Mapped[str | None] = mapped_column(String(100), default=None)
    world_name: Mapped[str | None] = mapped_column(String(255), default=None)
    location: Mapped[str | None] = mapped_column(String(150), default=None)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
