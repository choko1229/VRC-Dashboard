"""ゲームログ機能の統合テスト（取り込みAPIの認証、ページ表示、APIキー発行）。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_current_user
from app.models.dashboard_user import DashboardUser
from app.models.game_log_instance import GameLogInstance
from app.services import app_config_service


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


async def test_ingest_rejects_missing_authorization_header(client: AsyncClient) -> None:
    response = await client.post("/api/game-log/events", json={"events": []})
    assert response.status_code == 401


async def test_ingest_rejects_wrong_api_key(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with db_session_factory() as db:
        await app_config_service.generate_game_log_api_key(db)

    response = await client.post(
        "/api/game-log/events",
        json={"events": []},
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401


async def test_ingest_accepts_events_with_valid_api_key(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with db_session_factory() as db:
        raw_key = await app_config_service.generate_game_log_api_key(db)

    response = await client.post(
        "/api/game-log/events",
        json={
            "events": [
                {
                    "event_type": "instance_join",
                    "occurred_at": "2026-08-17T00:00:00+00:00",
                    "location": "wrld_a:1",
                    "world_id": "wrld_a",
                    "world_name": "World A",
                }
            ]
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": 1}

    async with db_session_factory() as db:
        instances = (await db.execute(select(GameLogInstance))).scalars().all()
        assert len(instances) == 1
        assert instances[0].world_name == "World A"


async def test_game_log_page_renders_for_logged_in_user(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    _override_current_user(fastapi_app, is_admin=False)

    response = await client.get("/game-log")

    assert response.status_code == 200
    assert "ゲームログ" in response.text
    # 非管理者にはエージェント連携の設定パネルを表示しない。
    assert "エージェント連携の設定" not in response.text


async def test_game_log_api_key_generation_forbidden_for_non_admin(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    _override_current_user(fastapi_app, is_admin=False)

    response = await client.post("/game-log/api-key")

    assert response.status_code == 403


async def test_game_log_api_key_generation_allowed_for_admin(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    _override_current_user(fastapi_app, is_admin=True)

    response = await client.post("/game-log/api-key")

    assert response.status_code == 200
    assert "この画面を離れると二度と表示されません" in response.text
