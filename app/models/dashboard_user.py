"""許可リストを通過し、少なくとも1度ログインしたDiscordユーザーのプロフィール。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DashboardUser(Base):
    __tablename__ = "dashboard_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_user_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    discord_username: Mapped[str] = mapped_column(String(100))
    discord_global_name: Mapped[str | None] = mapped_column(String(100), default=None)
    discord_avatar_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    # 許可リストが空の状態で最初にログインしたユーザーに自動付与される
    # （app.services.auth_service参照）。管理者はDiscordログイン許可リストの管理ができる。
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    first_login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
