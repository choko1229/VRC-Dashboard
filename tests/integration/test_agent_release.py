"""デスクトップエージェントの配布用ビルド管理（バージョン確認・アップロード・ダウンロード）の統合テスト。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_current_user
from app.models.dashboard_user import DashboardUser
from app.services import agent_release_service, app_config_service


@pytest.fixture(autouse=True)
def _isolate_release_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """テストが本物のdata/agent_releases/を汚さないよう、一時ディレクトリに差し替える。"""
    monkeypatch.setattr(agent_release_service, "_RELEASES_DIR", tmp_path / "agent_releases")


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
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    _override_current_user(fastapi_app, is_admin=False)

    response = await client.post(
        "/game-log/agent/release",
        data={"version": "0.2.0"},
        files={"file": ("VRCDashboardAgent.exe", b"dummy-exe-bytes")},
    )

    assert response.status_code == 403


async def test_admin_upload_then_agent_can_check_and_download(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _override_current_user(fastapi_app, is_admin=True)
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


async def test_agent_download_404_without_release(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with db_session_factory() as db:
        raw_key = await app_config_service.generate_game_log_api_key(db)

    response = await client.get(
        "/api/game-log/agent/download", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert response.status_code == 404
