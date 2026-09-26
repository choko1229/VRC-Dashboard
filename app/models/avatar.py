"""VRChatにアップロード済みのアバター（自分が所有するもののみ）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Avatar(Base):
    __tablename__ = "avatar"
    __table_args__ = (
        UniqueConstraint("dashboard_user_id", "vrchat_avatar_id", name="uq_avatar_owner"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 所有者（どのダッシュボードユーザーのVRChatアカウントのデータか）。複数人利用に対応するため、
    # ユーザー単位のデータは全てこの列で分離する。
    dashboard_user_id: Mapped[int] = mapped_column(
        ForeignKey("dashboard_user.id", ondelete="CASCADE"), index=True
    )
    vrchat_avatar_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(default=None)
    thumbnail_image_url: Mapped[str | None] = mapped_column(default=None)
    # VRChatが返す値をそのまま格納（例: Excellent/Good/Medium/Poor/VeryPoor）。
    # 非公式APIのため取得できない場合はNoneのままにする。プラットフォームごとに別カラム。
    performance_rank: Mapped[str | None] = mapped_column(String(20), default=None)  # PC
    performance_rank_android: Mapped[str | None] = mapped_column(String(20), default=None)
    performance_rank_ios: Mapped[str | None] = mapped_column(String(20), default=None)
    # "public" / "private"
    release_status: Mapped[str] = mapped_column(String(20), default="private")
    version: Mapped[int | None] = mapped_column(default=None)
    created_at_vrchat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    updated_at_vrchat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    notes: Mapped[str | None] = mapped_column(default=None)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
