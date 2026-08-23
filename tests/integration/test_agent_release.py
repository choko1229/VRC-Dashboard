"""デスクトップエージェントの配布用ビルド管理（バージョン確認・アップロード・ダウンロード）の統合テスト。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import generate_session_token, hash_session_token
from app.models.dashboard_session import DashboardSession
from app.models.dashboard_user import DashboardUser
from app.services import agent_release_service, app_config_service

_SESSION_COOKIE_NAME = "vrc_dashboard_session"


@pytest.fixture(autouse=True)
def _isolate_release_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """テストが本物のdata/agent_releases/を汚さないよう、一時ディレクトリに差し替える。"""
    monkeypatch.setattr(agent_release_service, "_RELEASES_DIR", tmp_path / "agent_releases")


async def _log_in_as(
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    *,
    is_admin: bool,
) -> None:
    """本物のセッションCookieでログインする（require_admin_or_release_tokenは依存関係の
    オーバーライドを経由せず直接Cookieを検証するため、実際のセッション機構を使う必要がある）。
    """
    async with db_session_factory() as db:
        user = DashboardUser(
            discord_user_id="test-user",
            discord_username="tester",
            is_admin=is_admin,
            first_login_at=datetime.now(UTC),
            last_login_at=datetime.now(UTC),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        raw_token = generate_session_token()
        db.add(
            DashboardSession(
                token_hash=hash_session_token(raw_token),
                dashboard_user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await db.commit()
    client.cookies.set(_SESSION_COOKIE_NAME, raw_token)


async def test_agent_version_without_release_reports_not_available(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with db_session_factory() as db:
        raw_key = await app_config_service.generate_game_log_api_key(db)

    response = await client.get(
        "/api/game-log/agent/version", headers={"Authorization": f"Bearer {raw_key}"}
    )

    assert response.status_code == 200
    assert response.json() == {"version": "0.0.0", "download_available": False}


async def test_agent_version_requires_api_key(client: AsyncClient) -> None:
    response = await client.get("/api/game-log/agent/version")
    assert response.status_code == 401


async def test_upload_release_forbidden_for_non_admin(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _log_in_as(client, db_session_factory, is_admin=False)

    response = await client.post(
        "/game-log/agent/release",
        data={"version": "0.2.0"},
        files={"file": ("VRCDashboardAgent.exe", b"dummy-exe-bytes")},
    )

    assert response.status_code == 403


async def test_upload_release_requires_admin_or_token(client: AsyncClient) -> None:
    response = await client.post(
        "/game-log/agent/release",
        data={"version": "0.2.0"},
        files={"file": ("VRCDashboardAgent.exe", b"dummy-exe-bytes")},
    )
    assert response.status_code == 302  # 未ログインは/loginへリダイレクト


async def test_upload_release_rejects_wrong_token(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with db_session_factory() as db:
        await app_config_service.generate_release_upload_token(db)

    response = await client.post(
        "/game-log/agent/release",
        data={"version": "0.2.0"},
        files={"file": ("VRCDashboardAgent.exe", b"dummy-exe-bytes")},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


async def test_admin_upload_then_agent_can_check_and_download(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _log_in_as(client, db_session_factory, is_admin=True)
    async with db_session_factory() as db:
        raw_key = await app_config_service.generate_game_log_api_key(db)

    upload_response = await client.post(
        "/game-log/agent/release",
        data={"version": "0.2.0"},
        files={"file": ("VRCDashboardAgent.exe", b"dummy-exe-bytes")},
    )
    assert upload_response.status_code == 200
    assert "v0.2.0" in upload_response.text

    version_response = await client.get(
        "/api/game-log/agent/version", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert version_response.json() == {"version": "0.2.0", "download_available": True}

    agent_download = await client.get(
        "/api/game-log/agent/download", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert agent_download.status_code == 200
    assert agent_download.content == b"dummy-exe-bytes"

    browser_download = await client.get("/game-log/agent/download")
    assert browser_download.status_code == 200
    assert browser_download.content == b"dummy-exe-bytes"


async def test_release_token_upload_works_without_login(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """build.ps1からの自動アップロード想定: ログインセッション無しでリリーストークンだけで通る。"""
    async with db_session_factory() as db:
        raw_token = await app_config_service.generate_release_upload_token(db)

    response = await client.post(
        "/game-log/agent/release",
        data={"version": "0.3.0"},
        files={"file": ("VRCDashboardAgent.exe", b"built-by-ci")},
        headers={"Authorization": f"Bearer {raw_token}"},
    )

    assert response.status_code == 200
    assert "v0.3.0" in response.text
    async with db_session_factory() as db:
        assert await agent_release_service.get_latest_version(db) == "0.3.0"


async def test_generate_and_revoke_release_token_admin_only(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _log_in_as(client, db_session_factory, is_admin=True)

    generate_response = await client.post("/game-log/release-token")
    assert generate_response.status_code == 200
    assert "この画面を離れると二度と表示されません" in generate_response.text

    revoke_response = await client.delete("/game-log/release-token")
    assert revoke_response.status_code == 200
    async with db_session_factory() as db:
        assert await app_config_service.is_release_upload_token_configured(db) is False


async def test_agent_download_404_without_release(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with db_session_factory() as db:
        raw_key = await app_config_service.generate_game_log_api_key(db)

    response = await client.get(
        "/api/game-log/agent/download", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert response.status_code == 404
