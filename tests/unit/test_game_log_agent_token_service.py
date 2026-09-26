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
        raw_token = await game_log_agent_token_service.create_token(db, 1, label="PC1")
        assert await game_log_agent_token_service.verify_token(db, raw_token) == 1


async def test_verify_rejects_unknown_token(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        assert await game_log_agent_token_service.verify_token(db, "unknown") is None


async def test_multiple_tokens_are_independent(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        token_a = await game_log_agent_token_service.create_token(db, 1, label="A")
        token_b = await game_log_agent_token_service.create_token(db, 1, label="B")

        tokens = await game_log_agent_token_service.list_tokens(db, 1)
        assert {t.label for t in tokens} == {"A", "B"}

        target = next(t for t in tokens if t.label == "A")
        await game_log_agent_token_service.revoke_token(db, 1, target.id)

        assert await game_log_agent_token_service.verify_token(db, token_a) is None
        assert await game_log_agent_token_service.verify_token(db, token_b) == 1


async def test_any_token_configured(db_session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with db_session_factory() as db:
        assert await game_log_agent_token_service.any_token_configured(db, 1) is False
        await game_log_agent_token_service.create_token(db, 1)
        assert await game_log_agent_token_service.any_token_configured(db, 1) is True


async def test_get_effective_now_returns_real_now_without_any_token(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        before = datetime.now(UTC)
        effective_now = await game_log_agent_token_service.get_effective_now(db, 1)
        after = datetime.now(UTC)
        assert before <= effective_now <= after


async def test_get_effective_now_returns_real_now_when_heartbeat_is_fresh(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        raw_token = await game_log_agent_token_service.create_token(db, 1)
        await game_log_agent_token_service.verify_token(db, raw_token)

        before = datetime.now(UTC)
        effective_now = await game_log_agent_token_service.get_effective_now(db, 1)
        after = datetime.now(UTC)
        assert before <= effective_now <= after


async def test_get_effective_now_caps_at_last_heartbeat_when_stale(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        db.add(
            GameLogAgentToken(
                dashboard_user_id=1,
                token_hash="dummy",
                last_used_at=datetime.now(UTC) - timedelta(hours=3),
            )
        )
        await db.commit()

        effective_now = await game_log_agent_token_service.get_effective_now(db, 1)

        assert effective_now < datetime.now(UTC) - timedelta(hours=2)


async def test_tokens_are_scoped_to_owner_dashboard_user(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """verify_tokenは所有者IDを返し、他ユーザーからの失効操作や疎通判定は影響しないこと。"""
    async with db_session_factory() as db:
        token_u1 = await game_log_agent_token_service.create_token(db, 1, label="U1")
        token_u2 = await game_log_agent_token_service.create_token(db, 2, label="U2")

        assert await game_log_agent_token_service.verify_token(db, token_u1) == 1
        assert await game_log_agent_token_service.verify_token(db, token_u2) == 2
        assert [t.label for t in await game_log_agent_token_service.list_tokens(db, 2)] == ["U2"]

        # ユーザー2がユーザー1のトークンIDを指定しても失効しない。
        u1_token_row = (await game_log_agent_token_service.list_tokens(db, 1))[0]
        await game_log_agent_token_service.revoke_token(db, 2, u1_token_row.id)
        assert await game_log_agent_token_service.verify_token(db, token_u1) == 1

        assert await game_log_agent_token_service.any_token_configured(db, 3) is False


async def test_get_effective_now_only_considers_given_users_tokens(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        stale = datetime.now(UTC) - timedelta(hours=3)
        db.add(GameLogAgentToken(dashboard_user_id=1, token_hash="stale", last_used_at=stale))
        await db.commit()

        # ユーザー2はトークンを持たないため、ユーザー1の古い疎通時刻に引きずられず実時刻になる。
        before = datetime.now(UTC)
        effective_now_u2 = await game_log_agent_token_service.get_effective_now(db, 2)
        assert effective_now_u2 >= before

        effective_now_u1 = await game_log_agent_token_service.get_effective_now(db, 1)
        assert effective_now_u1 < datetime.now(UTC) - timedelta(hours=2)
