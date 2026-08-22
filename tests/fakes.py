"""テスト用フェイク実装。"""

from __future__ import annotations

from app.notifications.base import NotificationPayload


class FakeNotificationSender:
    def __init__(self) -> None:
        self.sent: list[NotificationPayload] = []

    async def send(self, payload: NotificationPayload) -> None:
        self.sent.append(payload)
