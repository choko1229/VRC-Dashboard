"""ブラウザへのWeb Push通知送信。

pywebpushは同期(requestsベース)のためasyncio.to_threadでイベントループをブロックしないようにする。
購読が失効している(410 Gone / 404)場合はDBから削除する。
"""

from __future__ import annotations

import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.notifications.base import NotificationPayload
from app.services import webpush_service

logger = logging.getLogger(__name__)


class WebPushSender:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        vapid_private_key: str,
        vapid_public_key: str,
        vapid_contact_email: str,
    ) -> None:
        self._session_factory = session_factory
        self._vapid_private_key = vapid_private_key
        self._vapid_public_key = vapid_public_key
        self._vapid_contact_email = vapid_contact_email

    async def send(self, payload: NotificationPayload) -> None:
        if not self._vapid_private_key:
            logger.debug("VAPID鍵が未設定のためWeb Push送信をスキップします")
            return

        async with self._session_factory() as db:
            subscriptions = await webpush_service.list_subscriptions(db)

        body = json.dumps(
            {
                "title": "VRC事前確認ダッシュボード",
                "body": payload.message,
                "url": payload.link_path or "/",
            }
        )

        for subscription in subscriptions:
            subscription_info = {
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh_key, "auth": subscription.auth_key},
            }
            try:
                await asyncio.to_thread(
                    webpush,
                    subscription_info=subscription_info,
                    data=body,
                    vapid_private_key=self._vapid_private_key,
                    vapid_claims={"sub": self._vapid_contact_email},
                )
            except WebPushException as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code in (404, 410):
                    logger.info(
                        "Web Push購読が失効していたため削除します: %s", subscription.endpoint
                    )
                    async with self._session_factory() as db:
                        await webpush_service.delete_subscription(db, subscription.endpoint)
                else:
                    logger.warning("Web Push送信に失敗しました: %s", exc)
