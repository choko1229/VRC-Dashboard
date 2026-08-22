"""既存Discord BOTへの通知送信（暫定契約）。

既存BOTには現時点でHTTP受け口がないため、下記の契約をこちら側で定義し、
BOT側に将来実装してもらう想定（実装は本リポジトリのスコープ外）。

    POST {bot_url}/notify
    Authorization: Bearer {shared_secret}
    Content-Type: application/json
    Body: NotificationPayload

BOT側が未実装の間はタイムアウト/接続エラーになるが、これはログに記録するのみで
Pipelineリスナーやダッシュボード本体の動作をブロックしない。
"""

from __future__ import annotations

import logging

import httpx

from app.notifications.base import NotificationPayload

logger = logging.getLogger(__name__)


class DiscordNotifySender:
    def __init__(self, *, bot_url: str, shared_secret: str, timeout: float = 10.0) -> None:
        self._bot_url = bot_url.rstrip("/")
        self._shared_secret = shared_secret
        self._timeout = timeout

    async def send(self, payload: NotificationPayload) -> None:
        if not self._bot_url:
            logger.debug("Discord通知先URLが未設定のため送信をスキップします")
            return

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._bot_url}/notify",
                    headers={"Authorization": f"Bearer {self._shared_secret}"},
                    json=payload.model_dump(mode="json"),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "Discord通知の送信に失敗しました（処理は継続します）: type=%s error=%s",
                payload.type,
                exc,
            )
