"""VRChat Pipeline(WebSocket)への常時接続・再接続・イベント処理。

再接続ポリシー（ユーザー確認済み）:
  初回5秒 → 指数バックオフで最大60秒間隔、リトライ回数無制限、
  連続10回失敗でDiscordへ通知する。

複数人利用に対応するため、VRChatにログインしているダッシュボードユーザーごとに
1本ずつ接続を持つ（PipelineManagerが1ユーザー分、PipelineRegistryが全ユーザー分を管理する）。
受信したイベントは、その接続の所有者のデータとしてDBへ反映する。
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import websockets
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.notifications.base import NotificationPayload, NotificationSender
from app.schemas.vrchat import VRChatUser, parse_world_id_from_location
from app.services import friends_service, vrchat_notification_service, vrchat_session_service
from app.services.vrchat.client import VRChatAuthError, VRChatClient

logger = logging.getLogger(__name__)

_PIPELINE_URL = "wss://pipeline.vrchat.cloud/"

# (db, sender, 接続の所有者のdashboard_user_id, content)
EventHandler = Callable[
    [AsyncSession, NotificationSender, int, dict[str, Any]], Awaitable[None]
]
NotificationSenderFactory = Callable[[AsyncSession], Awaitable[NotificationSender]]
AuthCookieProvider = Callable[[], Awaitable[str | None]]
UserAgentProvider = Callable[[], Awaitable[str]]
SelfLocationSeeder = Callable[[str, str], Awaitable[None]]
AuthInvalidHandler = Callable[[], Awaitable[None]]


def _extract_world_thumbnail_url(world: Any) -> str | None:
    """PipelineのworldオブジェクトからカードUIの背景に使うサムネイルURLを取り出す。

    `thumbnailImageUrl`（小さいプレビュー用）を優先し、無ければ`imageUrl`にフォールバックする。
    """
    if not isinstance(world, dict):
        return None
    thumbnail = world.get("thumbnailImageUrl") or world.get("imageUrl")
    return thumbnail if isinstance(thumbnail, str) else None


def _extract_display_name(*candidates: object) -> str | None:
    """最初に見つかった非空文字列のdisplayNameを返す。

    どの候補にも無い場合はNone（呼び出し側はuser_id等へのフォールバックをしないこと。
    フォールバック値がfriend.display_nameに永続化されるとUUIDがそのまま表示され続ける
    不具合になる——本番で実際に発生した不具合）。
    """
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


async def _on_friend_online(
    db: AsyncSession, sender: NotificationSender, user_id: int, content: dict[str, Any]
) -> None:
    raw_user = content.get("user")
    user = raw_user if isinstance(raw_user, dict) else {}
    vrchat_user_id = content.get("userId") or user.get("id")
    if not isinstance(vrchat_user_id, str):
        return
    display_name = _extract_display_name(user.get("displayName"), content.get("displayName"))
    location = content.get("location") or user.get("location")
    world = content.get("world")
    world_name = world.get("name") if isinstance(world, dict) else None

    await friends_service.handle_friend_online(
        db,
        sender,
        user_id,
        vrchat_user_id=vrchat_user_id,
        display_name=display_name,
        location=location if isinstance(location, str) else None,
        world_name=world_name if isinstance(world_name, str) else None,
        world_thumbnail_url=_extract_world_thumbnail_url(world),
    )


async def _on_friend_active(
    db: AsyncSession, sender: NotificationSender, user_id: int, content: dict[str, Any]
) -> None:
    """接続中だがワールドに滞在していない（Web/メニュー等）状態への遷移。"""
    vrchat_user_id = content.get("userId")
    if not isinstance(vrchat_user_id, str):
        return
    display_name = _extract_display_name(content.get("displayName"))
    await friends_service.handle_friend_active(
        db, sender, user_id, vrchat_user_id=vrchat_user_id, display_name=display_name
    )


async def _on_friend_offline(
    db: AsyncSession, sender: NotificationSender, user_id: int, content: dict[str, Any]
) -> None:
    vrchat_user_id = content.get("userId")
    if not isinstance(vrchat_user_id, str):
        return
    display_name = _extract_display_name(content.get("displayName"))
    await friends_service.handle_friend_offline(
        db, sender, user_id, vrchat_user_id=vrchat_user_id, display_name=display_name
    )


async def _on_friend_location(
    db: AsyncSession, sender: NotificationSender, user_id: int, content: dict[str, Any]
) -> None:
    vrchat_user_id = content.get("userId")
    if not isinstance(vrchat_user_id, str):
        return
    display_name = _extract_display_name(content.get("displayName"))
    location = content.get("location")
    world = content.get("world")
    world_name = world.get("name") if isinstance(world, dict) else None

    await friends_service.handle_friend_location_change(
        db,
        sender,
        user_id,
        vrchat_user_id=vrchat_user_id,
        display_name=display_name,
        location=location if isinstance(location, str) else None,
        world_name=world_name if isinstance(world_name, str) else None,
        world_thumbnail_url=_extract_world_thumbnail_url(world),
    )


async def _on_friend_update(
    db: AsyncSession, _sender: NotificationSender, user_id: int, content: dict[str, Any]
) -> None:
    user = content.get("user")
    if not isinstance(user, dict):
        return
    try:
        vrchat_user = VRChatUser.model_validate(user)
    except Exception:
        logger.warning("friend-updateイベントのユーザー情報パースに失敗しました")
        return
    await friends_service.handle_friend_status_update(db, user_id, vrchat_user=vrchat_user)


async def _on_user_location(
    db: AsyncSession, _sender: NotificationSender, user_id: int, content: dict[str, Any]
) -> None:
    """自分（操作者）自身の現在地の変化。「同じインスタンス」判定に使う。"""
    location = content.get("location")
    world = content.get("world")
    world_name = world.get("name") if isinstance(world, dict) else None
    location_str = location if isinstance(location, str) else None
    await vrchat_session_service.update_self_location(
        db,
        user_id,
        location=location_str,
        world_id=parse_world_id_from_location(location_str),
        world_name=world_name if isinstance(world_name, str) else None,
    )


async def _on_vrchat_notification_event(
    db: AsyncSession,
    _sender: NotificationSender,
    user_id: int,
    content: dict[str, Any],
    *,
    event_type: str,
) -> None:
    """VRChat自体の通知ログ（招待/フレンドリクエスト/グループイベント等）への取込。

    複数のPipelineイベント種別を1つの汎用ハンドラで受け、実際の解釈は
    vrchat_notification_service.ingest()に委譲する（app.services.vrchat_notification_service
    参照。仕様が非公開なイベント種別も多いため、そちらで防御的にパースする）。
    """
    await vrchat_notification_service.ingest(
        db, user_id, pipeline_event=event_type, content=content
    )


_EVENT_HANDLERS: dict[str, EventHandler] = {
    "friend-online": _on_friend_online,
    "friend-active": _on_friend_active,
    "friend-offline": _on_friend_offline,
    "friend-location": _on_friend_location,
    "friend-update": _on_friend_update,
    "user-location": _on_user_location,
    "notification": functools.partial(_on_vrchat_notification_event, event_type="notification"),
    "notification-v2": functools.partial(
        _on_vrchat_notification_event, event_type="notification-v2"
    ),
    "notification-v2-delete": functools.partial(
        _on_vrchat_notification_event, event_type="notification-v2-delete"
    ),
    "see-notification": functools.partial(
        _on_vrchat_notification_event, event_type="see-notification"
    ),
    "hide-notification": functools.partial(
        _on_vrchat_notification_event, event_type="hide-notification"
    ),
    "response-notification": functools.partial(
        _on_vrchat_notification_event, event_type="response-notification"
    ),
    "friend-add": functools.partial(_on_vrchat_notification_event, event_type="friend-add"),
    "economy-update": functools.partial(
        _on_vrchat_notification_event, event_type="economy-update"
    ),
    "instance-queue-joined": functools.partial(
        _on_vrchat_notification_event, event_type="instance-queue-joined"
    ),
    "instance-queue-ready": functools.partial(
        _on_vrchat_notification_event, event_type="instance-queue-ready"
    ),
    "group-joined": functools.partial(_on_vrchat_notification_event, event_type="group-joined"),
    "group-left": functools.partial(_on_vrchat_notification_event, event_type="group-left"),
    "group-member-updated": functools.partial(
        _on_vrchat_notification_event, event_type="group-member-updated"
    ),
    "group-role-updated": functools.partial(
        _on_vrchat_notification_event, event_type="group-role-updated"
    ),
}


class PipelineManager:
    """1ダッシュボードユーザー分のPipeline接続のライフサイクル（開始/停止/再接続）を管理する。

    各Provider（auth cookie/UA/通知送信手段）は、このユーザー用に束縛済みのものを受け取る
    （PipelineRegistry経由で生成する）。
    """

    def __init__(
        self,
        *,
        dashboard_user_id: int,
        session_factory: async_sessionmaker[AsyncSession],
        notification_sender_factory: NotificationSenderFactory,
        get_auth_cookie: AuthCookieProvider,
        get_user_agent: UserAgentProvider,
        initial_reconnect_seconds: float,
        max_reconnect_seconds: float,
        notify_after_failures: int,
        seed_self_location: SelfLocationSeeder | None = None,
        on_auth_invalid: AuthInvalidHandler | None = None,
    ) -> None:
        self._dashboard_user_id = dashboard_user_id
        self._session_factory = session_factory
        self._notification_sender_factory = notification_sender_factory
        self._get_auth_cookie = get_auth_cookie
        self._get_user_agent = get_user_agent
        self._seed_self_location = seed_self_location or self._default_seed_self_location
        self._on_auth_invalid = on_auth_invalid
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
        self._task = asyncio.create_task(
            self._run_forever(), name=f"vrchat-pipeline-{self._dashboard_user_id}"
        )
        logger.info("Pipelineリスナーを起動しました (user=%d)", self._dashboard_user_id)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Pipelineリスナーを停止しました (user=%d)", self._dashboard_user_id)

    async def _run_forever(self) -> None:
        delay = self._initial_reconnect_seconds
        while True:
            try:
                await self._connect_and_listen()
                self._consecutive_failures = 0
                delay = self._initial_reconnect_seconds
            except asyncio.CancelledError:
                raise
            except VRChatAuthError:
                # セッション切れ（401）は再接続しても回復しないため、セッションを無効化して
                # 接続を諦める。ユーザーは次回ページを開いた際にVRChatへの再ログインを求められる。
                logger.warning(
                    "VRChatのセッションが失効しているためPipeline接続を停止します (user=%d)",
                    self._dashboard_user_id,
                )
                if self._on_auth_invalid is not None:
                    await self._on_auth_invalid()
                return
            except Exception as exc:  # noqa: BLE001 再接続ループを継続させるため意図的に広く捕捉する
                self._consecutive_failures += 1
                logger.warning(
                    "Pipeline接続でエラーが発生しました（user=%d, %d回連続、%.0f秒後に再試行）: %s",
                    self._dashboard_user_id,
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
        user_agent = await self._get_user_agent()

        await self._seed_self_location(auth_cookie, user_agent)

        url = f"{_PIPELINE_URL}?authToken={auth_cookie}"
        # VRChatはUser-Agent未設定/デフォルト値のリクエストを403で拒否するため、
        # websocketsライブラリの既定User-Agentではなく設定済みのVRChat用UAを明示する。
        async with websockets.connect(
            url, user_agent_header=user_agent, open_timeout=15, close_timeout=5
        ) as ws:
            logger.info("VRChat Pipelineに接続しました (user=%d)", self._dashboard_user_id)
            async for raw_message in ws:
                await self._handle_message(raw_message)

    async def _default_seed_self_location(self, auth_cookie: str, user_agent: str) -> None:
        """接続確立時点で、自分（操作者）の現在地をREST APIから補完する。

        Pipelineの"user-location"イベントは実際にワールドを移動した瞬間にしか
        送られない。そのため接続時点で既にどこかのワールドに滞在している場合、
        次にワールドを移動するまでself_locationがNoneのままとなり、サイドバー/
        フレンド一覧の「同じインスタンス」区分が機能しない不具合があった。

        セッション切れ（VRChatAuthError）のみは呼び出し元へ伝播させ、Pipeline接続を停止させる
        （それ以外の失敗は現在地が補完されないだけのため、接続自体は続行する）。
        """
        client = VRChatClient(user_agent=user_agent, auth_cookie=auth_cookie)
        try:
            current_user = await client.get_current_user()
            world_id = parse_world_id_from_location(current_user.location)
            world_name = await client.get_world_name(world_id) if world_id else None
            async with self._session_factory() as db:
                await vrchat_session_service.update_self_location(
                    db,
                    self._dashboard_user_id,
                    location=current_user.location,
                    world_id=world_id,
                    world_name=world_name,
                )
        except VRChatAuthError:
            raise
        except Exception:
            logger.warning("接続時点の自分の現在地取得に失敗しました", exc_info=True)
        finally:
            await client.close()

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
                await handler(db, sender, self._dashboard_user_id, content)
            except Exception:
                logger.exception(
                    "Pipelineイベント処理中にエラーが発生しました: user=%d type=%s",
                    self._dashboard_user_id,
                    message_type,
                )


class PipelineRegistry:
    """ダッシュボードユーザーごとのPipelineManagerをまとめて管理する。

    `manager_factory`はユーザーIDから、そのユーザー用に束縛済みのPipelineManagerを生成する
    （app.mainで組み立てる）。
    """

    def __init__(self, *, manager_factory: Callable[[int], PipelineManager]) -> None:
        self._manager_factory = manager_factory
        self._managers: dict[int, PipelineManager] = {}

    def is_running(self, user_id: int) -> bool:
        manager = self._managers.get(user_id)
        return manager is not None and manager.is_running

    def start(self, user_id: int) -> None:
        manager = self._managers.get(user_id)
        if manager is None:
            manager = self._manager_factory(user_id)
            self._managers[user_id] = manager
        manager.start()

    async def restart(self, user_id: int) -> None:
        """再ログイン時等、新しい認証情報で接続し直す。"""
        await self.stop(user_id)
        self.start(user_id)

    async def stop(self, user_id: int) -> None:
        manager = self._managers.pop(user_id, None)
        if manager is not None:
            await manager.stop()

    async def stop_all(self) -> None:
        for user_id in list(self._managers):
            await self.stop(user_id)
