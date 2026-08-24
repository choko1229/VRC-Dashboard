"""通知送信の抽象化。

DiscordのBOT側にはまだHTTPの受け口がないため、本アプリ側は下記のプロトコルに対して
実装しておき、将来BOT側の受け口や別の通知手段（Web Push等）に差し替えやすくする。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

NotificationType = Literal[
    "friend_online",
    "friend_offline",
    "friend_world_change",
    "pipeline_reconnect_failure",
]


class NotificationPayload(BaseModel):
    type: NotificationType
    friend_vrchat_user_id: str | None = None
    friend_display_name: str | None = None
    world_name: str | None = None
    occurred_at: datetime
    message: str

    @property
    def link_path(self) -> str | None:
        """ブラウザ通知クリック時の遷移先（フレンド関連の通知はフレンド詳細へ）。"""
        if self.friend_vrchat_user_id:
            return f"/friends/{self.friend_vrchat_user_id}"
        return None


class NotificationSender(Protocol):
    """通知送信手段の共通インターフェース。"""

    async def send(self, payload: NotificationPayload) -> None: ...
