"""ユーザーPC上のVRChatクライアントのログファイルから収集した、滞在インスタンス単位のログ。

ローカルエージェント（local_agent/）がVRChatの出力ログを解析し、インスタンスへの入退室を
このテーブルの1行として送信する。同じワールド/インスタンスへ再入室した場合も別行として扱う
（VRCXのゲームログ画面と同様、訪問ごとに区切って表示するため）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GameLogInstance(Base):
    __tablename__ = "game_log_instance"
    __table_args__ = (Index("ix_game_log_instance_joined_at", "joined_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    location: Mapped[str] = mapped_column(String(150))
    world_id: Mapped[str | None] = mapped_column(String(100), default=None)
    world_name: Mapped[str | None] = mapped_column(String(255), default=None)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 次のインスタンスへのjoinログや明示的なleaveログが観測された時点で埋まる。
    # ログ欠落等により埋まらないまま残ることもある。
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
