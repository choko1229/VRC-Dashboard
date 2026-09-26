"""許可リストから外されたユーザーのアクセスを即時に断つことの結合テスト。"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.models.dashboard_session import DashboardSession
from app.models.discord_allowlist_entry import DiscordAllowlistEntry
from app.services import game_log_agent_token_service, session_service, vrchat_session_service
from tests.fakes import login_as, make_dashboard_user, seed_allowlisted_user, seed_vrchat_session


class _FakePipelineRegistry:
    def __init__(self) -> None:
        self.stopped: list[int] = []

    async def stop(self, user_id: int) -> None:
        self.stopped.append(user_id)


async def _allowlist_entry_id(
    db_session_factory: async_sessionmaker[AsyncSession], discord_user_id: str
) -> int:
    async with db_session_factory() as db:
        return (
            await db.execute(
                select(DiscordAllowlistEntry.id).where(
                    DiscordAllowlistEntry.discord_user_id == discord_user_id
                )
            )
        ).scalar_one()


async def test_deleting_allowlist_entry_revokes_all_access_of_that_user(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_allowlisted_user(db_session_factory, user_id=2)
    await seed_vrchat_session(db_session_factory, user_id=2)
    await seed_vrchat_session(db_session_factory, user_id=3)
    async with db_session_factory() as db:
        await session_service.create_session(
            db, dashboard_user_id=2, ttl_seconds=3600, user_agent=None, ip_address=None
        )
        token_user2 = await game_log_agent_token_service.create_token(db, 2, label="PC")
        await game_log_agent_token_service.create_token(db, 3, label="他人のPC")

    login_as(fastapi_app, user_id=1, is_admin=True)
    registry = _FakePipelineRegistry()
    fastapi_app.state.pipeline_registry = registry
    target = make_dashboard_user(user_id=2)
    entry_id = await _allowlist_entry_id(db_session_factory, target.discord_user_id)

    response = await client.delete(f"/settings/allowlist/{entry_id}")

    assert response.status_code == 200
    assert target.discord_user_id not in response.text
    assert registry.stopped == [2]
    async with db_session_factory() as db:
        sessions = (
            (
                await db.execute(
                    select(DashboardSession).where(DashboardSession.dashboard_user_id == 2)
                )
            )
            .scalars()
            .all()
        )
        assert sessions and all(s.revoked_at is not None for s in sessions)
        assert await vrchat_session_service.get_active_session(db, 2) is None
        assert await game_log_agent_token_service.verify_token(db, token_user2) is None
        assert await game_log_agent_token_service.list_tokens(db, 2) == []
        # 他のユーザーには影響しない。
        assert await vrchat_session_service.get_active_session(db, 3) is not None
        assert len(await game_log_agent_token_service.list_tokens(db, 3)) == 1


async def test_admin_cannot_remove_own_allowlist_entry(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_allowlisted_user(db_session_factory, user_id=1, is_admin=True)
    login_as(fastapi_app, user_id=1, is_admin=True)
    fastapi_app.state.pipeline_registry = _FakePipelineRegistry()
    me = make_dashboard_user(user_id=1)
    entry_id = await _allowlist_entry_id(db_session_factory, me.discord_user_id)

    response = await client.delete(f"/settings/allowlist/{entry_id}")

    assert response.status_code == 200
    assert "自分自身の許可は取り消せません" in response.text
    async with db_session_factory() as db:
        assert await db.get(DiscordAllowlistEntry, entry_id) is not None


async def test_removed_user_is_logged_out_even_with_a_live_session_cookie(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """削除画面を経由せずに許可リストから外された場合（DB直接操作等）も締め出す。"""
    await seed_allowlisted_user(db_session_factory, user_id=2)
    await seed_vrchat_session(db_session_factory, user_id=2)
    async with db_session_factory() as db:
        raw_token = await session_service.create_session(
            db, dashboard_user_id=2, ttl_seconds=3600, user_agent=None, ip_address=None
        )
    client.cookies.set(get_settings().session_cookie_name, raw_token)

    assert (await client.get("/friends", follow_redirects=False)).status_code == 200

    entry_id = await _allowlist_entry_id(
        db_session_factory, make_dashboard_user(user_id=2).discord_user_id
    )
    async with db_session_factory() as db:
        await db.delete(await db.get(DiscordAllowlistEntry, entry_id))
        await db.commit()

    response = await client.get("/friends", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_agent_token_of_removed_user_is_rejected(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_allowlisted_user(db_session_factory, user_id=2)
    async with db_session_factory() as db:
        raw_token = await game_log_agent_token_service.create_token(db, 2, label="PC")
    headers = {"Authorization": f"Bearer {raw_token}"}
    assert (await client.get("/api/agent/commands", headers=headers)).status_code == 200

    entry_id = await _allowlist_entry_id(
        db_session_factory, make_dashboard_user(user_id=2).discord_user_id
    )
    async with db_session_factory() as db:
        await db.delete(await db.get(DiscordAllowlistEntry, entry_id))
        await db.commit()

    assert (await client.get("/api/agent/commands", headers=headers)).status_code == 401


async def test_pipeline_startup_skips_users_removed_from_allowlist(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_allowlisted_user(db_session_factory, user_id=1)
    await seed_vrchat_session(db_session_factory, user_id=1)
    # ユーザー2はDB上に存在しVRChatセッションも有効だが、許可リストに載っていない。
    async with db_session_factory() as db:
        db.add(make_dashboard_user(user_id=2))
        await db.commit()
    await seed_vrchat_session(db_session_factory, user_id=2)

    async with db_session_factory() as db:
        assert await vrchat_session_service.list_user_ids_with_active_session(db) == [1]
