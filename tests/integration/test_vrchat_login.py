"""Discordアカウントごとの VRChat ログイン（/settings/vrchat/login）の結合テスト。

VRChat APIとの通信・初回同期はモンキーパッチで差し替え、Pipelineはフェイクのレジストリで
起動/停止の呼び出しだけを記録する。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.vrchat import VRChatUser
from app.services import vrchat_session_service, vrchat_sync_service
from app.services.vrchat import client as vrchat_client_module
from tests.fakes import login_as, seed_vrchat_session


class _FakePipelineRegistry:
    def __init__(self) -> None:
        self.restarted: list[int] = []
        self.stopped: list[int] = []

    async def restart(self, user_id: int) -> None:
        self.restarted.append(user_id)

    async def stop(self, user_id: int) -> None:
        self.stopped.append(user_id)


def _patch_vrchat_login(monkeypatch: pytest.MonkeyPatch, *, vrchat_user_id: str) -> None:
    async def fake_login(self: Any, username: str, password: str) -> VRChatUser:
        return VRChatUser(id=vrchat_user_id, display_name=f"表示名-{vrchat_user_id}")

    async def fake_close(self: Any) -> None:
        return None

    async def noop_sync(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(vrchat_client_module.VRChatClient, "login", fake_login)
    monkeypatch.setattr(vrchat_client_module.VRChatClient, "close", fake_close)
    monkeypatch.setattr(vrchat_sync_service, "full_friends_sync", noop_sync)
    monkeypatch.setattr(vrchat_sync_service, "full_avatars_sync", noop_sync)


async def test_vrchat_login_saves_session_for_current_user_and_redirects_home(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login_as(fastapi_app, user_id=2, vrchat_linked=False)
    registry = _FakePipelineRegistry()
    fastapi_app.state.pipeline_registry = registry
    _patch_vrchat_login(monkeypatch, vrchat_user_id="usr_user2")

    response = await client.post(
        "/settings/vrchat/login", data={"username": "u", "password": "p"}
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/"
    assert registry.restarted == [2]
    async with db_session_factory() as db:
        session = await vrchat_session_service.get_active_session(db, 2)
        assert session is not None
        assert session.vrchat_user_id == "usr_user2"
        assert await vrchat_session_service.get_active_session(db, 1) is None


async def test_vrchat_login_rejects_account_already_linked_by_another_user(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同じVRChatアカウントを別のDiscordアカウントで共有すると、フレンド・通知が重複して
    取り込まれるため拒否する。"""
    await seed_vrchat_session(db_session_factory, user_id=1, vrchat_user_id="usr_shared")
    login_as(fastapi_app, user_id=2, vrchat_linked=False)
    registry = _FakePipelineRegistry()
    fastapi_app.state.pipeline_registry = registry
    _patch_vrchat_login(monkeypatch, vrchat_user_id="usr_shared")

    response = await client.post(
        "/settings/vrchat/login", data={"username": "u", "password": "p"}
    )

    assert response.status_code == 409
    assert "別のDiscordアカウントで既に連携されています" in response.text
    assert "HX-Redirect" not in response.headers
    assert registry.restarted == []
    async with db_session_factory() as db:
        assert await vrchat_session_service.get_active_session(db, 2) is None
        # 既存ユーザーのセッションは影響を受けない。
        assert await vrchat_session_service.get_active_session(db, 1) is not None


async def test_vrchat_logout_only_affects_current_user(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_vrchat_session(db_session_factory, user_id=1)
    await seed_vrchat_session(db_session_factory, user_id=2)
    login_as(fastapi_app, user_id=2, vrchat_linked=False)
    registry = _FakePipelineRegistry()
    fastapi_app.state.pipeline_registry = registry

    response = await client.post("/settings/vrchat/logout")

    assert response.status_code == 200
    assert registry.stopped == [2]
    async with db_session_factory() as db:
        assert await vrchat_session_service.get_active_session(db, 2) is None
        assert await vrchat_session_service.get_active_session(db, 1) is not None
