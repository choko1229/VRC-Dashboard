"""アバター用の共通タグリスト（自由入力ではなくここから選択する形式）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tag(Base):
    __tablename__ = "tag"
    __table_args__ = (
        UniqueConstraint("dashboard_user_id", "name", name="uq_tag_owner"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 所有者（どのダッシュボードユーザーのVRChatアカウントのデータか）。複数人利用に対応するため、
    # ユーザー単位のデータは全てこの列で分離する。
    dashboard_user_id: Mapped[int] = mapped_column(
        ForeignKey("dashboard_user.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))
    color: Mapped[str | None] = mapped_column(String(20), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
