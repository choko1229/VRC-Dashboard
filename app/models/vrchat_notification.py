"""VRChat自体の通知（招待・フレンドリクエスト・グループイベント等）のログ。

Pipelineの複数のイベント種別（notification/notification-v2/economy-update/group-*等）を
まとめて1テーブルに集約する。仕様が非公開なイベント種別も多いため、フィールド抽出に
失敗した/未知の種類は notification_type に生のtype文字列、raw_details に生JSONを
保存し、一覧側で汎用フォールバック表示する（app.services.vrchat_notification_service参照）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VRChatNotification(Base):
    __tablename__ = "vrchat_notification"
    __table_args__ = (Index("ix_vrchat_notification_occurred_at", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # VRChat側の通知ID（Pipeline再配信/REST再取込に対してupsertで冪等にするための一意キー）。
    vrchat_notification_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 受信元のPipelineイベント種別: notification / notification-v2 / economy-update /
    # group-joined 等。
    pipeline_event: Mapped[str] = mapped_column(String(30))
    # VRChatの生のtype文字列: invite / friendRequest / group.announcement / economy_update 等。
    notification_type: Mapped[str] = mapped_column(String(50), index=True)
    sender_user_id: Mapped[str | None] = mapped_column(String(64), default=None)
    sender_display_name: Mapped[str | None] = mapped_column(String(100), default=None)
    group_name: Mapped[str | None] = mapped_column(String(100), default=None)
    image_url: Mapped[str | None] = mapped_column(default=None)
    message: Mapped[str | None] = mapped_column(default=None)
    # 招待先インスタンス等。「参加」アクション（デスクトップエージェント経由でVRChatを起動）に使う。
    location: Mapped[str | None] = mapped_column(String(150), default=None)
    # 生JSON文字列。未対応の種類の表示や、将来の個別対応追加のために保持する。
    raw_details: Mapped[str | None] = mapped_column(default=None)
    # 削除操作の論理削除フラグ（VRChat側hide/delete APIが失敗しても一覧からは消す）。
    is_hidden: Mapped[bool] = mapped_column(default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
