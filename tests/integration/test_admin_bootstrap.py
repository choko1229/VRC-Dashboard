"""フェーズ6: 初回ログインの管理者自動昇格、および管理者限定画面のアクセス制御。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_current_user
from app.models.dashboard_user import DashboardUser
from app.routers import auth as auth_router
from app.schemas.discord import DiscordTokenResponse
from app.schemas.discord import DiscordUser as DiscordUserSchema
from app.services import auth_service


def _override_current_user(fastapi_app: FastAPI, *, is_admin: bool) -> None:
    async def fake_current_user() -> DashboardUser:
        return DashboardUser(
            id=1,
            discord_user_id="123456789012345678",
            discord_username="tester",
            is_admin=is_admin,
            first_login_at=datetime.now(UTC),
            last_login_at=datetime.now(UTC),
        )

    fastapi_app.dependency_overrides[get_current_user] = fake_current_user


async def test_allowlist_page_forbidden_for_non_admin(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    _override_current_user(fastapi_app, is_admin=False)

    response = await client.get("/settings/allowlist")

    assert response.status_code == 403
    assert "管理者権限" in response.text


async def test_allowlist_page_allowed_for_admin(fastapi_app: FastAPI, client: AsyncClient) -> None:
    _override_current_user(fastapi_app, is_admin=True)

    response = await client.get("/settings/allowlist")

    assert response.status_code == 200
    assert "ユーザー管理" in response.text


async def test_add_allowlist_entry_forbidden_for_non_admin(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    _override_current_user(fastapi_app, is_admin=False)

    response = await client.post(
        "/settings/allowlist", data={"discord_user_id": "999", "label": ""}
    )

    assert response.status_code == 403


def _mock_discord_oauth_exchange(
    monkeypatch: pytest.MonkeyPatch, *, discord_user_id: str, username: str
) -> None:
    async def fake_exchange(**_kwargs: object) -> DiscordTokenResponse:
        return DiscordTokenResponse(
            access_token="fake-token", token_type="Bearer", expires_in=600, scope="identify"
        )

    async def fake_fetch(*, access_token: str) -> DiscordUserSchema:
        return DiscordUserSchema(id=discord_user_id, username=username)

    monkeypatch.setattr(auth_router, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(auth_router, "fetch_current_discord_user", fake_fetch)


async def test_discord_callback_first_login_becomes_admin(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _mock_discord_oauth_exchange(monkeypatch, discord_user_id="777", username="first-user")

    client.cookies.set("oauth_state", "expected-state")
    response = await client.get(
        "/auth/discord/callback",
        params={"code": "dummy", "state": "expected-state"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/"

    async with db_session_factory() as db:
        assert await auth_service.is_allowlisted(db, "777") is True


async def test_discord_callback_second_login_not_auto_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _mock_discord_oauth_exchange(monkeypatch, discord_user_id="777", username="first-user")
    client.cookies.set("oauth_state", "state-one")
    await client.get(
        "/auth/discord/callback",
        params={"code": "dummy", "state": "state-one"},
        follow_redirects=False,
    )

    _mock_discord_oauth_exchange(monkeypatch, discord_user_id="888", username="second-user")
    client.cookies.set("oauth_state", "state-two")
    response = await client.get(
        "/auth/discord/callback",
        params={"code": "dummy", "state": "state-two"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    async with db_session_factory() as db:
        assert await auth_service.is_allowlisted(db, "888") is False
