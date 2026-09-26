"""VRChatのお気に入りグループ（フレンド）を反映するグループ。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FriendGroup(Base):
    __tablename__ = "friend_group"
    __table_args__ = (
        UniqueConstraint("dashboard_user_id", "vrchat_group_id", name="uq_friend_group_owner"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 所有者（どのダッシュボードユーザーのVRChatアカウントのデータか）。複数人利用に対応するため、
    # ユーザー単位のデータは全てこの列で分離する。
    dashboard_user_id: Mapped[int] = mapped_column(
        ForeignKey("dashboard_user.id", ondelete="CASCADE"), index=True
    )
    # VRChat側のお気に入りグループID。ダッシュボード独自のローカルグループはNULL。
    vrchat_group_id: Mapped[str | None] = mapped_column(String(100), default=None)
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # "synced": VRChat側から取得した読み取り専用グループ / "local": ダッシュボード独自グループ
    source: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
