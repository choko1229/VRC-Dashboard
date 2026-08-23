"""デスクトップエージェント（desktop_agent/）がゲームログ取り込みに使う認証トークン。

1台のPC・1個のエージェントプロセスにつき1トークンを想定した多対応モデル（旧: app_settingに
単一ハッシュを1個だけ保持する方式）。複数のPCでエージェントを動かしても、後から追加した
デバイスが既存デバイスのトークンを無効化してしまわないようにするため、テーブルとして管理する。

ブラウザでのログイン→承認（device_auth_service参照）で発行されるほか、ハッシュのみDBに
保存し生トークンは発行時の一度きりしか見えない点はdashboard_session/discord_allowlist_entry
と同じ方針。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GameLogAgentToken(Base):
    __tablename__ = "game_log_agent_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # ブラウザでの承認時に入力できる任意のラベル（例: 「自宅PC」）。
    label: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
