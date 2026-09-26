"""フェーズ2: PipelineイベントハンドラのJSONパース〜DB反映のユニットテスト。"""

from __future__ import annotations

from typing import Any

import pytest
import websockets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.friend import Friend
from app.models.vrchat_notification import VRChatNotification
from app.services.vrchat import pipeline
from tests.fakes import FakeNotificationSender


async def test_on_friend_online_updates_friend(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        content = {
            "userId": "usr_1",
            "user": {"id": "usr_1", "displayName": "Alice"},
            "location": "wrld_abc:12345",
            "world": {"name": "Alice's World", "thumbnailImageUrl": "https://example.com/t.png"},
        }
        await pipeline._on_friend_online(db, sender, 1, content)

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_1"))
        ).scalar_one()
        assert friend.is_online is True
        assert friend.current_world_name == "Alice's World"
        assert friend.current_world_thumbnail_url == "https://example.com/t.png"


def test_extract_world_thumbnail_url_falls_back_to_image_url() -> None:
    assert (
        pipeline._extract_world_thumbnail_url({"imageUrl": "https://example.com/full.png"})
        == "https://example.com/full.png"
    )
    assert pipeline._extract_world_thumbnail_url(None) is None
    assert pipeline._extract_world_thumbnail_url({}) is None


def test_extract_display_name_returns_none_without_fallback_to_user_id() -> None:
    """本番で発生した不具合の回帰テスト: displayNameが無い場合にuser_id(usr_xxx)へ
    フォールバックしてはいけない（friend.display_nameへ永続化されるとUUIDが
    表示され続けてしまうため）。
    """
    assert pipeline._extract_display_name(None, "") is None
    assert pipeline._extract_display_name(None, "Alice") == "Alice"
    assert pipeline._extract_display_name("Bob", "Alice") == "Bob"


async def test_on_friend_active_without_display_name_does_not_overwrite_existing_name(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """friend-activeイベントにdisplayNameが含まれない場合、既存の表示名を
    user_id(usr_xxx)で上書きしないことの回帰テスト。
    """
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await pipeline._on_friend_online(
            db, sender, 1, {"userId": "usr_active_1", "user": {"displayName": "Carol"}}
        )
        await pipeline._on_friend_active(db, sender, 1, {"userId": "usr_active_1"})

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_active_1"))
        ).scalar_one()
        assert friend.display_name == "Carol"
        assert friend.online_state == "active"


async def test_on_friend_online_without_display_name_does_not_overwrite_existing_name(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await pipeline._on_friend_online(
            db, sender, 1, {"userId": "usr_online_1", "user": {"displayName": "Dave"}}
        )
        # 2回目のfriend-onlineでdisplayNameが省略されているケース。
        await pipeline._on_friend_online(db, sender, 1, {"userId": "usr_online_1", "user": {}})

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_online_1"))
        ).scalar_one()
        assert friend.display_name == "Dave"


async def test_on_friend_online_first_sighting_without_display_name_uses_user_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """新規フレンド(初見)でdisplayNameが取れない場合のみ、暫定的にuser_idを使う
    （次にdisplayName付きのイベントが来れば置き換わる）。
    """
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await pipeline._on_friend_online(db, sender, 1, {"userId": "usr_new_1", "user": {}})

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_new_1"))
        ).scalar_one()
        assert friend.display_name == "usr_new_1"


async def test_on_friend_offline_updates_friend(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await pipeline._on_friend_online(
            db, sender, 1, {"userId": "usr_2", "user": {"displayName": "Bob"}}
        )
        await pipeline._on_friend_offline(db, sender, 1, {"userId": "usr_2"})

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_2"))
        ).scalar_one()
        assert friend.is_online is False


async def test_on_friend_location_updates_world(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        content = {
            "userId": "usr_3",
            "displayName": "Carol",
            "location": "wrld_new:999",
            "world": {"name": "New World"},
        }
        await pipeline._on_friend_location(db, sender, 1, content)

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_3"))
        ).scalar_one()
        assert friend.current_world_id == "wrld_new"
        assert friend.current_world_name == "New World"


async def test_on_friend_update_changes_status(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        content = {"user": {"id": "usr_4", "displayName": "Dave", "status": "busy"}}
        await pipeline._on_friend_update(db, sender, 1, content)

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_4"))
        ).scalar_one()
        assert friend.activity_status == "busy"


async def test_handle_message_dispatches_to_registered_handler(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import json

    manager = pipeline.PipelineManager(
        dashboard_user_id=1,
        session_factory=db_session_factory,
        notification_sender_factory=lambda db: _fake_sender_factory(),
        get_auth_cookie=_none_cookie,
        get_user_agent=_fake_user_agent,
        initial_reconnect_seconds=1,
        max_reconnect_seconds=1,
        notify_after_failures=1,
    )
    raw_message = json.dumps(
        {
            "type": "friend-offline",
            "content": json.dumps({"userId": "usr_5", "displayName": "Eve"}),
        }
    )
    await manager._handle_message(raw_message)

    async with db_session_factory() as db:
        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_5"))
        ).scalar_one()
        assert friend.is_online is False


async def test_connect_and_listen_passes_configured_user_agent(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VRChatはデフォルト(websocketsライブラリ既定)のUser-Agentを403で拒否するため、
    設定済みのVRChat用UAがPipeline接続時にも渡されることを確認する。
    """
    captured: dict[str, Any] = {}

    class _FakeConnection:
        async def __aenter__(self) -> _FakeConnection:
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            return None

        def __aiter__(self) -> _FakeConnection:
            return self

        async def __anext__(self) -> str:
            raise StopAsyncIteration

    def fake_connect(url: str, **kwargs: Any) -> _FakeConnection:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeConnection()

    monkeypatch.setattr(websockets, "connect", fake_connect)

    async def fake_auth_cookie() -> str | None:
        return "dummy-auth-cookie"

    manager = pipeline.PipelineManager(
        dashboard_user_id=1,
        session_factory=db_session_factory,
        notification_sender_factory=lambda db: _fake_sender_factory(),
        get_auth_cookie=fake_auth_cookie,
        get_user_agent=_fake_user_agent,
        initial_reconnect_seconds=1,
        max_reconnect_seconds=1,
        notify_after_failures=1,
        seed_self_location=_noop_seed_self_location,
    )
    await manager._connect_and_listen()

    assert captured["kwargs"]["user_agent_header"] == "VRC-Dashboard-Test/1.0"


async def test_seed_self_location_updates_session_from_current_user(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """接続時点で既にワールドに滞在している場合でも、REST APIから
    self_locationが補完され「同じインスタンス」判定が機能することを確認する。
    """
    from app.models.vrchat_session import VRChatSession
    from app.schemas.vrchat import VRChatUser
    from app.services.vrchat import client as vrchat_client_module

    async def fake_get_current_user(self: Any) -> VRChatUser:
        return VRChatUser(id="usr_self", display_name="Self", location="wrld_abc:123")

    async def fake_get_world_name(self: Any, world_id: str) -> str | None:
        return "Abc World"

    async def fake_close(self: Any) -> None:
        return None

    monkeypatch.setattr(
        vrchat_client_module.VRChatClient, "get_current_user", fake_get_current_user
    )
    monkeypatch.setattr(vrchat_client_module.VRChatClient, "get_world_name", fake_get_world_name)
    monkeypatch.setattr(vrchat_client_module.VRChatClient, "close", fake_close)

    async with db_session_factory() as db:
        db.add(
            VRChatSession(
                dashboard_user_id=1,
                vrchat_user_id="usr_self",
                vrchat_display_name="Self",
                auth_cookie_encrypted="dummy",
                is_valid=True,
            )
        )
        await db.commit()

    manager = pipeline.PipelineManager(
        dashboard_user_id=1,
        session_factory=db_session_factory,
        notification_sender_factory=lambda db: _fake_sender_factory(),
        get_auth_cookie=_none_cookie,
        get_user_agent=_fake_user_agent,
        initial_reconnect_seconds=1,
        max_reconnect_seconds=1,
        notify_after_failures=1,
    )
    await manager._default_seed_self_location("dummy-auth-cookie", "VRC-Dashboard-Test/1.0")

    async with db_session_factory() as db:
        session = (
            await db.execute(select(VRChatSession).where(VRChatSession.is_valid.is_(True)))
        ).scalar_one()
        assert session.self_location == "wrld_abc:123"
        assert session.self_world_id == "wrld_abc"
        assert session.self_world_name == "Abc World"


async def _noop_seed_self_location(auth_cookie: str, user_agent: str) -> None:
    return None


async def test_on_notification_event_ingests_via_notification_service(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        content = {"id": "not_pipeline_1", "type": "friendRequest", "senderUsername": "Zoe"}
        handler = pipeline._EVENT_HANDLERS["notification"]
        await handler(db, sender, 1, content)

        row = (
            await db.execute(
                select(VRChatNotification).where(
                    VRChatNotification.vrchat_notification_id == "not_pipeline_1"
                )
            )
        ).scalar_one()
        assert row.notification_type == "friendRequest"
        assert row.sender_display_name == "Zoe"


async def test_on_economy_update_event_routes_to_notification_service(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        handler = pipeline._EVENT_HANDLERS["economy-update"]
        await handler(db, sender, 1, {"description": "残高が更新されました"})

        row = (await db.execute(select(VRChatNotification))).scalars().one()
        assert row.pipeline_event == "economy-update"
        assert row.message == "残高が更新されました"


async def _fake_sender_factory() -> FakeNotificationSender:
    return FakeNotificationSender()


async def _none_cookie() -> str | None:
    return None


async def _fake_user_agent() -> str:
    return "VRC-Dashboard-Test/1.0"


def _build_manager(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_id: int,
    **overrides: Any,
) -> pipeline.PipelineManager:
    kwargs: dict[str, Any] = {
        "dashboard_user_id": user_id,
        "session_factory": db_session_factory,
        "notification_sender_factory": lambda db: _fake_sender_factory(),
        # 認証Cookie無し→_connect_and_listenが即座に失敗するため、ネットワークには触れない。
        "get_auth_cookie": _none_cookie,
        "get_user_agent": _fake_user_agent,
        "initial_reconnect_seconds": 60,
        "max_reconnect_seconds": 60,
        "notify_after_failures": 1000,
    }
    kwargs.update(overrides)
    return pipeline.PipelineManager(**kwargs)


async def test_handle_message_applies_event_to_managers_own_user(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """受信したイベントは、そのPipeline接続の所有者のデータとしてDBへ反映される。"""
    import json

    manager = _build_manager(db_session_factory, 2)
    await manager._handle_message(
        json.dumps({"type": "friend-offline", "content": {"userId": "usr_owned"}})
    )

    async with db_session_factory() as db:
        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_owned"))
        ).scalar_one()
        assert friend.dashboard_user_id == 2


async def test_pipeline_registry_starts_and_stops_per_user(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    created: list[int] = []

    def factory(user_id: int) -> pipeline.PipelineManager:
        created.append(user_id)
        return _build_manager(db_session_factory, user_id)

    registry = pipeline.PipelineRegistry(manager_factory=factory)
    try:
        registry.start(1)
        registry.start(2)
        # 起動済みユーザーの再startでは新しいManagerを作らない。
        registry.start(1)
        assert created == [1, 2]
        assert registry.is_running(1) is True
        assert registry.is_running(2) is True
        assert registry.is_running(3) is False

        await registry.stop(1)
        assert registry.is_running(1) is False
        assert registry.is_running(2) is True

        await registry.restart(2)
        assert created == [1, 2, 2]
        assert registry.is_running(2) is True
    finally:
        await registry.stop_all()
    assert registry.is_running(1) is False
    assert registry.is_running(2) is False


async def test_run_forever_stops_and_calls_on_auth_invalid_when_seed_raises_auth_error(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """接続時の現在地補完でセッション切れ(401)が判明した場合、再接続ループを止めて
    on_auth_invalidを呼ぶ（再接続しても回復しないため）。
    """
    import asyncio

    from app.services.vrchat.client import VRChatAuthError

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(pipeline.asyncio, "sleep", fake_sleep)

    def fail_connect(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("セッション切れ時にWebSocket接続してはいけない")

    monkeypatch.setattr(websockets, "connect", fail_connect)

    seed_calls = 0

    async def raising_seed(auth_cookie: str, user_agent: str) -> None:
        nonlocal seed_calls
        seed_calls += 1
        raise VRChatAuthError("401")

    async def fake_auth_cookie() -> str | None:
        return "expired-cookie"

    invalidated: list[bool] = []

    async def on_auth_invalid() -> None:
        invalidated.append(True)

    manager = _build_manager(
        db_session_factory,
        1,
        get_auth_cookie=fake_auth_cookie,
        seed_self_location=raising_seed,
        on_auth_invalid=on_auth_invalid,
    )
    await asyncio.wait_for(manager._run_forever(), timeout=5)

    assert seed_calls == 1
    assert invalidated == [True]
    assert sleeps == []


async def test_run_forever_keeps_retrying_on_other_errors(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """セッション切れ以外の失敗では再接続ループを継続する（on_auth_invalidは呼ばない）。"""
    import asyncio

    class _StopLoop(Exception):
        pass

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) >= 3:
            raise _StopLoop

    monkeypatch.setattr(pipeline.asyncio, "sleep", fake_sleep)

    invalidated: list[bool] = []

    async def on_auth_invalid() -> None:
        invalidated.append(True)

    manager = _build_manager(
        db_session_factory,
        1,
        initial_reconnect_seconds=1,
        max_reconnect_seconds=4,
        on_auth_invalid=on_auth_invalid,
    )
    with pytest.raises(_StopLoop):
        await asyncio.wait_for(manager._run_forever(), timeout=5)

    assert sleeps == [1, 2, 4]
    assert invalidated == []
