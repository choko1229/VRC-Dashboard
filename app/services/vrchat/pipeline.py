"""VRChat Pipeline(WebSocket)への常時接続・再接続・イベント処理。

再接続ポリシー（ユーザー確認済み）:
  初回5秒 → 指数バックオフで最大60秒間隔、リトライ回数無制限、
  連続10回失敗でDiscordへ通知する。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import websockets
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.notifications.base import NotificationPayload, NotificationSender
from app.schemas.vrchat import VRChatUser
from app.services import friends_service

logger = logging.getLogger(__name__)

_PIPELINE_URL = "wss://pipeline.vrchat.cloud/"

EventHandler = Callable[[AsyncSession, NotificationSender, dict[str, Any]], Awaitable[None]]
NotificationSenderFactory = Callable[[AsyncSession], Awaitable[NotificationSender]]
AuthCookieProvider = Callable[[], Awaitable[str | None]]


async def _on_friend_online(
    db: AsyncSession, sender: NotificationSender, content: dict[str, Any]
) -> None:
    raw_user = content.get("user")
    user = raw_user if isinstance(raw_user, dict) else {}
    user_id = content.get("userId") or user.get("id")
    if not isinstance(user_id, str):
        return
    display_name = user.get("displayName") or content.get("displayName") or user_id
    location = content.get("location") or user.get("location")
    world = content.get("world")
    world_name = world.get("name") if isinstance(world, dict) else None

    await friends_service.handle_friend_online(
        db,
        sender,
        vrchat_user_id=user_id,
        display_name=str(display_name),
        location=location if isinstance(location, str) else None,
        world_name=world_name if isinstance(world_name, str) else None,
    )


async def _on_friend_offline(
    db: AsyncSession, sender: NotificationSender, content: dict[str, Any]
) -> None:
    user_id = content.get("userId")
    if not isinstance(user_id, str):
        return
    display_name = content.get("displayName") or user_id
    await friends_service.handle_friend_offline(
        db, sender, vrchat_user_id=user_id, display_name=str(display_name)
    )


async def _on_friend_location(
    db: AsyncSession, sender: NotificationSender, content: dict[str, Any]
) -> None:
    user_id = content.get("userId")
    if not isinstance(user_id, str):
        return
    display_name = content.get("displayName") or user_id
    location = content.get("location")
    world = content.get("world")
    world_name = world.get("name") if isinstance(world, dict) else None

    await friends_service.handle_friend_location_change(
        db,
        sender,
        vrchat_user_id=user_id,
        display_name=str(display_name),
        location=location if isinstance(location, str) else None,
        world_name=world_name if isinstance(world_name, str) else None,
    )


async def _on_friend_update(
    db: AsyncSession, _sender: NotificationSender, content: dict[str, Any]
) -> None:
    user = content.get("user")
    if not isinstance(user, dict):
        return
    try:
        vrchat_user = VRChatUser.model_validate(user)
    except Exception:
        logger.warning("friend-updateイベントのユーザー情報パースに失敗しました")
        return
    await friends_service.handle_friend_status_update(db, vrchat_user=vrchat_user)


_EVENT_HANDLERS: dict[str, EventHandler] = {
    "friend-online": _on_friend_online,
    "friend-offline": _on_friend_offline,
    "friend-location": _on_friend_location,
    "friend-update": _on_friend_update,
}


class PipelineManager:
    """Pipeline接続のライフサイクル（開始/停止/再接続）を管理する。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        notification_sender_factory: NotificationSenderFactory,
        get_auth_cookie: AuthCookieProvider,
        initial_reconnect_seconds: float,
        max_reconnect_seconds: float,
        notify_after_failures: int,
    ) -> None:
        self._session_factory = session_factory
        self._notification_sender_factory = notification_sender_factory
        self._get_auth_cookie = get_auth_cookie
        self._initial_reconnect_seconds = initial_reconnect_seconds
        self._max_reconnect_seconds = max_reconnect_seconds
        self._notify_after_failures = notify_after_failures

        self._task: asyncio.Task[None] | None = None
        self._consecutive_failures = 0

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._consecutive_failures = 0
        self._task = asyncio.create_task(self._run_forever(), name="vrchat-pipeline")
        logger.info("Pipelineリスナーを起動しました")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Pipelineリスナーを停止しました")

    async def _run_forever(self) -> None:
        delay = self._initial_reconnect_seconds
        while True:
            try:
                await self._connect_and_listen()
                self._consecutive_failures = 0
                delay = self._initial_reconnect_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 再接続ループを継続させるため意図的に広く捕捉する
                self._consecutive_failures += 1
                logger.warning(
                    "Pipeline接続でエラーが発生しました（%d回連続、%.0f秒後に再試行）: %s",
                    self._consecutive_failures,
                    delay,
                    exc,
                )
                if self._consecutive_failures == self._notify_after_failures:
                    await self._notify_reconnect_failure()

            await asyncio.sleep(delay)
            delay = min(delay * 2, self._max_reconnect_seconds)

    async def _notify_reconnect_failure(self) -> None:
        async with self._session_factory() as db:
            sender = await self._notification_sender_factory(db)
            await sender.send(
                NotificationPayload(
                    type="pipeline_reconnect_failure",
                    occurred_at=datetime.now(UTC),
                    message=(
                        f"VRChat Pipelineへの再接続に{self._consecutive_failures}回連続で"
                        "失敗しています。VRChatのセッションが失効している可能性があります。"
                    ),
                )
            )

    async def _connect_and_listen(self) -> None:
        auth_cookie = await self._get_auth_cookie()
        if not auth_cookie:
            raise RuntimeError("VRChatの認証セッションがありません")

        url = f"{_PIPELINE_URL}?authToken={auth_cookie}"
        async with websockets.connect(url, open_timeout=15, close_timeout=5) as ws:
            logger.info("VRChat Pipelineに接続しました")
            async for raw_message in ws:
                await self._handle_message(raw_message)

    async def _handle_message(self, raw_message: str | bytes) -> None:
        try:
            message = json.loads(raw_message)
        except ValueError:
            logger.warning("Pipelineメッセージのパースに失敗しました")
            return

        message_type = message.get("type")
        raw_content = message.get("content")
        content: dict[str, Any]
        if isinstance(raw_content, str):
            try:
                content = json.loads(raw_content)
            except ValueError:
                logger.warning(
                    "Pipelineメッセージのcontentパースに失敗しました: type=%s", message_type
                )
                return
        elif isinstance(raw_content, dict):
            content = raw_content
        else:
            content = {}

        handler = _EVENT_HANDLERS.get(message_type or "")
        if handler is None:
            return

        async with self._session_factory() as db:
            sender = await self._notification_sender_factory(db)
            try:
                await handler(db, sender, content)
            except Exception:
                logger.exception(
                    "Pipelineイベント処理中にエラーが発生しました: type=%s", message_type
                )
