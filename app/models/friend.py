"""VRChatフレンドの最新状態（ダッシュボード表示用の高速参照）。

VRChat自体には"online"というstatus値は存在しない
（statusは active/join me/ask me/busy/offline のいずれか）ため、
オンライン判定はPipelineのfriend-online/friend-offlineイベントに基づく`is_online`で別管理する。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Friend(Base):
    __tablename__ = "friend"

    id: Mapped[int] = mapped_column(primary_key=True)
    vrchat_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    is_online: Mapped[bool] = mapped_column(default=False)
    # VRChatの実際のstatus値: active / join me / ask me / busy / offline（気分ステータス）
    activity_status: Mapped[str] = mapped_column(String(20), default="offline")
    # VRChatの接続状態: online（ワールドに滞在中）/ active（接続中だがワールド不明）/ offline
    # activity_statusとは別概念（VRChat APIの"state"フィールドに対応）。
    # サイドバーの「同じインスタンス/オンライン/アクティブ」区分に使う。
    online_state: Mapped[str] = mapped_column(String(10), default="offline")
    # VRChatのステータスメッセージ（ユーザーが自由入力する一言）。
    status_message: Mapped[str | None] = mapped_column(String(255), default=None)
    current_world_id: Mapped[str | None] = mapped_column(String(100), default=None)
    current_world_name: Mapped[str | None] = mapped_column(String(255), default=None)
    current_location: Mapped[str | None] = mapped_column(String(150), default=None)
    current_avatar_thumbnail_url: Mapped[str | None] = mapped_column(default=None)
    last_seen_online_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
