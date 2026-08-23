"""フェーズ2: PipelineイベントハンドラのJSONパース〜DB反映のユニットテスト。"""

from __future__ import annotations

from typing import Any

import pytest
import websockets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.friend import Friend
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
        await pipeline._on_friend_online(db, sender, content)

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


async def test_on_friend_offline_updates_friend(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await pipeline._on_friend_online(
            db, sender, {"userId": "usr_2", "user": {"displayName": "Bob"}}
        )
        await pipeline._on_friend_offline(db, sender, {"userId": "usr_2"})

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
        await pipeline._on_friend_location(db, sender, content)

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
        await pipeline._on_friend_update(db, sender, content)

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_4"))
        ).scalar_one()
        assert friend.activity_status == "busy"


async def test_handle_message_dispatches_to_registered_handler(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import json

    manager = pipeline.PipelineManager(
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
                vrchat_user_id="usr_self",
                vrchat_display_name="Self",
                auth_cookie_encrypted="dummy",
                is_valid=True,
            )
        )
        await db.commit()

    manager = pipeline.PipelineManager(
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


async def _fake_sender_factory() -> FakeNotificationSender:
    return FakeNotificationSender()


async def _none_cookie() -> str | None:
    return None


async def _fake_user_agent() -> str:
    return "VRC-Dashboard-Test/1.0"
