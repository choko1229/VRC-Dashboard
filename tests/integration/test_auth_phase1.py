"""フェーズ1: 認証まわりの結合テスト。"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import SecretCipher
from app.services import app_config_service

_TEST_FERNET_KEY = "gdsF_NX-iLtl8QLOwmQyFeEdQtOmWXiAlHD4kTrLuh4="


async def _configure_discord_oauth(db_session_factory: async_sessionmaker[AsyncSession]) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    async with db_session_factory() as db:
        await app_config_service.set_discord_oauth_config(
            db, cipher, client_id="test-client-id", client_secret="test-secret"
        )


async def test_login_page_redirects_to_setup_when_not_configured(client: AsyncClient) -> None:
    response = await client.get("/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/setup"


async def test_login_page_renders_once_discord_oauth_configured(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _configure_discord_oauth(db_session_factory)

    response = await client.get("/login")
    assert response.status_code == 200
    assert "Discordでログイン" in response.text


async def test_setup_page_redirects_to_login_once_already_configured(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _configure_discord_oauth(db_session_factory)

    response = await client.get("/setup", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_dashboard_redirects_when_unauthenticated(client: AsyncClient) -> None:
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_settings_allowlist_redirects_when_unauthenticated(client: AsyncClient) -> None:
    response = await client.get("/settings/allowlist", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_discord_callback_rejects_state_mismatch(client: AsyncClient) -> None:
    client.cookies.set("oauth_state", "expected-state")
    response = await client.get(
        "/auth/discord/callback", params={"code": "dummy", "state": "wrong-state"}
    )
    assert response.status_code == 400
