"""ゲームログ取り込み用トークン（マルチデバイス対応）のユニットテスト。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.game_log_agent_token import GameLogAgentToken
from app.services import game_log_agent_token_service


async def test_create_and_verify_token(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        raw_token = await game_log_agent_token_service.create_token(db, label="PC1")
        assert await game_log_agent_token_service.verify_token(db, raw_token) is True


async def test_verify_rejects_unknown_token(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        assert await game_log_agent_token_service.verify_token(db, "unknown") is False


async def test_multiple_tokens_are_independent(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        token_a = await game_log_agent_token_service.create_token(db, label="A")
        token_b = await game_log_agent_token_service.create_token(db, label="B")

        tokens = await game_log_agent_token_service.list_tokens(db)
        assert {t.label for t in tokens} == {"A", "B"}

        target = next(t for t in tokens if t.label == "A")
        await game_log_agent_token_service.revoke_token(db, target.id)

        assert await game_log_agent_token_service.verify_token(db, token_a) is False
        assert await game_log_agent_token_service.verify_token(db, token_b) is True


async def test_any_token_configured(db_session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with db_session_factory() as db:
        assert await game_log_agent_token_service.any_token_configured(db) is False
        await game_log_agent_token_service.create_token(db)
        assert await game_log_agent_token_service.any_token_configured(db) is True


async def test_get_effective_now_returns_real_now_without_any_token(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        before = datetime.now(UTC)
        effective_now = await game_log_agent_token_service.get_effective_now(db)
        after = datetime.now(UTC)
        assert before <= effective_now <= after


async def test_get_effective_now_returns_real_now_when_heartbeat_is_fresh(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        raw_token = await game_log_agent_token_service.create_token(db)
        await game_log_agent_token_service.verify_token(db, raw_token)

        before = datetime.now(UTC)
        effective_now = await game_log_agent_token_service.get_effective_now(db)
        after = datetime.now(UTC)
        assert before <= effective_now <= after


async def test_get_effective_now_caps_at_last_heartbeat_when_stale(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        db.add(
            GameLogAgentToken(
                token_hash="dummy",
                last_used_at=datetime.now(UTC) - timedelta(hours=3),
            )
        )
        await db.commit()

        effective_now = await game_log_agent_token_service.get_effective_now(db)

        assert effective_now < datetime.now(UTC) - timedelta(hours=2)
