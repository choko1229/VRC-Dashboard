"""デスクトップエージェント（desktop_agent/）へのPC側操作の委譲キュー。

サーバー単体では実行できない操作（例: VRChatクライアントを起動してインスタンスに参加する）を、
既にペアリング済みのエージェントに委譲するためのコマンドキュー。単一ユーザー前提の
ダッシュボードのため、ユーザー紐付けは不要なグローバルな1本のキューとして扱う
（game_log_agent_tokenと同様の設計方針）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentCommand(Base):
    __tablename__ = "agent_command"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 現状 "join_instance" のみ。
    command_type: Mapped[str] = mapped_column(String(30))
    # 例: {"location": "wrld_x:123~..."}
    payload_json: Mapped[str] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / done / failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
