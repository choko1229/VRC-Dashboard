"""フェーズ1: 許可リスト照合・ダッシュボードユーザーUpsertのユニットテスト。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.discord_allowlist_entry import DiscordAllowlistEntry
from app.schemas.discord import DiscordUser
from app.services import auth_service


async def test_is_allowlisted_true_and_false(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        db.add(DiscordAllowlistEntry(discord_user_id="111"))
        await db.commit()

        assert await auth_service.is_allowlisted(db, "111") is True
        assert await auth_service.is_allowlisted(db, "999") is False


async def test_upsert_dashboard_user_creates_then_updates(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        discord_user = DiscordUser(id="222", username="alice", global_name="Alice", avatar=None)

        created = await auth_service.upsert_dashboard_user(db, discord_user)
        assert created.discord_username == "alice"
        first_login_at = created.first_login_at

        updated_discord_user = DiscordUser(
            id="222", username="alice-new", global_name="Alice N", avatar="hash123"
        )
        updated = await auth_service.upsert_dashboard_user(db, updated_discord_user)

        assert updated.id == created.id
        assert updated.discord_username == "alice-new"
        assert updated.discord_avatar_hash == "hash123"
        assert updated.first_login_at == first_login_at
