"""複数の通知送信手段へまとめて配信するコンポジット。

個々のsenderの送信失敗は他のsenderの送信を妨げない（全件試行してから戻る）。
"""

from __future__ import annotations

import logging

from app.notifications.base import NotificationPayload, NotificationSender

logger = logging.getLogger(__name__)


class CompositeNotificationSender:
    def __init__(self, senders: list[NotificationSender]) -> None:
        self._senders = senders

    async def send(self, payload: NotificationPayload) -> None:
        for sender in self._senders:
            try:
                await sender.send(payload)
            except Exception:
                logger.exception(
                    "通知送信中に想定外のエラーが発生しました: sender=%s type=%s",
                    type(sender).__name__,
                    payload.type,
                )
