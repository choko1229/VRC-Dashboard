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


async def test_allowlist_is_empty(db_session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with db_session_factory() as db:
        assert await auth_service.allowlist_is_empty(db) is True

        db.add(DiscordAllowlistEntry(discord_user_id="111"))
        await db.commit()

        assert await auth_service.allowlist_is_empty(db) is False


async def test_bootstrap_first_admin_adds_allowlist_entry(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await auth_service.bootstrap_first_admin(db, "333", label="Bootstrap User")

        assert await auth_service.is_allowlisted(db, "333") is True


async def test_upsert_dashboard_user_is_admin_only_applied_on_creation(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        discord_user = DiscordUser(id="444", username="bob", global_name=None, avatar=None)

        created = await auth_service.upsert_dashboard_user(db, discord_user, is_admin=True)
        assert created.is_admin is True

        # 再ログイン時にis_adminを渡さなくても、既存の権限は維持される（上書きされない）。
        updated = await auth_service.upsert_dashboard_user(db, discord_user)
        assert updated.is_admin is True
