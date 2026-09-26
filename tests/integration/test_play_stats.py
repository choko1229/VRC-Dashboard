"""プレイ記録ページ（/stats）の統合テスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.game_log_instance import GameLogInstance
from tests.fakes import login_as


def _log_in(fastapi_app: FastAPI) -> None:
    login_as(fastapi_app, user_id=1)


async def test_play_stats_requires_login(client: AsyncClient) -> None:
    response = await client.get("/stats", follow_redirects=False)
    assert response.status_code == 302


async def test_play_stats_shows_empty_state_without_records(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    _log_in(fastapi_app)
    response = await client.get("/stats")
    assert response.status_code == 200
    assert "記録がまだありません" in response.text


async def test_play_stats_shows_summary_with_records(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _log_in(fastapi_app)
    async with db_session_factory() as db:
        db.add(
            GameLogInstance(
                dashboard_user_id=1,
                location="wrld_a:1",
                world_id="wrld_a",
                world_name="テストワールド",
                joined_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
                left_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
            )
        )
        await db.commit()

    response = await client.get("/stats")
    assert response.status_code == 200
    assert "総プレイ時間" in response.text
    assert "テストワールド" in response.text


async def test_play_stats_excludes_other_users_records(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """複数人利用: 他ユーザーのゲームログはプレイ記録に集計されない。"""
    async with db_session_factory() as db:
        db.add(
            GameLogInstance(
                dashboard_user_id=2,
                location="wrld_b:1",
                world_id="wrld_b",
                world_name="他人のワールド",
                joined_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
                left_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
            )
        )
        await db.commit()

    _log_in(fastapi_app)
    response = await client.get("/stats")
    assert response.status_code == 200
    assert "他人のワールド" not in response.text
    assert "記録がまだありません" in response.text
