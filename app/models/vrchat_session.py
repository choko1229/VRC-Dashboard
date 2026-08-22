"""VRChatへのログインセッション（authCookie/twoFactorAuthCookie）。

アプリ運用上は単一の有効な行のみを想定する（単一ユーザー前提のダッシュボードのため）。
トークン本体はアプリ層でFernet暗号化してから保存する（app.core.security.SecretCipher）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VRChatSession(Base):
    __tablename__ = "vrchat_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    vrchat_user_id: Mapped[str] = mapped_column(String(64))
    vrchat_display_name: Mapped[str] = mapped_column(String(100))
    auth_cookie_encrypted: Mapped[str] = mapped_column()
    two_factor_cookie_encrypted: Mapped[str | None] = mapped_column(default=None)
    obtained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)

    # 自分（ダッシュボード操作者）自身の現在地。Pipelineの"user-location"イベントで更新する。
    # 「同じインスタンス」のフレンド判定（サイドバー表示）に使う。
    self_location: Mapped[str | None] = mapped_column(String(150), default=None)
    self_world_id: Mapped[str | None] = mapped_column(String(100), default=None)
    self_world_name: Mapped[str | None] = mapped_column(String(255), default=None)
