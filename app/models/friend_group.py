"""VRChatのお気に入りグループ（フレンド）を反映するグループ。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FriendGroup(Base):
    __tablename__ = "friend_group"

    id: Mapped[int] = mapped_column(primary_key=True)
    # VRChat側のお気に入りグループID。ダッシュボード独自のローカルグループはNULL。
    vrchat_group_id: Mapped[str | None] = mapped_column(String(100), unique=True, default=None)
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # "synced": VRChat側から取得した読み取り専用グループ / "local": ダッシュボード独自グループ
    source: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
