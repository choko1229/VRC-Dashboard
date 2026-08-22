"""フェーズ1: セッション発行・検証・失効のユニットテスト。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.dashboard_user import DashboardUser
from app.services import session_service


async def _create_user(db: AsyncSession, discord_user_id: str) -> DashboardUser:
    user = DashboardUser(discord_user_id=discord_user_id, discord_username="tester")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_create_and_validate_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        user = await _create_user(db, "1")
        raw_token = await session_service.create_session(
            db, dashboard_user_id=user.id, ttl_seconds=3600, user_agent=None, ip_address=None
        )
        fetched = await session_service.get_user_for_session_token(db, raw_token)
        assert fetched is not None
        assert fetched.id == user.id


async def test_revoked_session_is_rejected(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        user = await _create_user(db, "2")
        raw_token = await session_service.create_session(
            db, dashboard_user_id=user.id, ttl_seconds=3600, user_agent=None, ip_address=None
        )
        await session_service.revoke_session(db, raw_token)
        fetched = await session_service.get_user_for_session_token(db, raw_token)
        assert fetched is None


async def test_expired_session_is_rejected(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        user = await _create_user(db, "3")
        raw_token = await session_service.create_session(
            db, dashboard_user_id=user.id, ttl_seconds=-10, user_agent=None, ip_address=None
        )
        fetched = await session_service.get_user_for_session_token(db, raw_token)
        assert fetched is None


async def test_unknown_token_is_rejected(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        fetched = await session_service.get_user_for_session_token(db, "does-not-exist")
        assert fetched is None
