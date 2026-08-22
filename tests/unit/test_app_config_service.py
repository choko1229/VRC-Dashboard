"""外部連携設定(Discord OAuth/VRChat連絡先/VAPID鍵)のDB管理のユニットテスト。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import SecretCipher
from app.services import app_config_service

_TEST_FERNET_KEY = "gdsF_NX-iLtl8QLOwmQyFeEdQtOmWXiAlHD4kTrLuh4="


async def test_discord_oauth_config_roundtrip(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    async with db_session_factory() as db:
        assert await app_config_service.is_discord_oauth_configured(db) is False

        await app_config_service.set_discord_oauth_config(
            db, cipher, client_id="abc123", client_secret="s3cr3t"
        )

        assert await app_config_service.is_discord_oauth_configured(db) is True
        client_id, client_secret = await app_config_service.get_discord_oauth_config(db, cipher)
        assert client_id == "abc123"
        assert client_secret == "s3cr3t"


async def test_vrchat_user_agent_defaults_and_override(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        default_ua = await app_config_service.get_vrchat_user_agent(db)
        assert default_ua

        await app_config_service.set_vrchat_user_agent(db, "MyApp/1.0 (me@example.com)")
        updated_ua = await app_config_service.get_vrchat_user_agent(db)
        assert updated_ua == "MyApp/1.0 (me@example.com)"


async def test_vapid_keys_are_generated_once_and_persisted(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    async with db_session_factory() as db:
        private_1, public_1 = await app_config_service.get_or_create_vapid_keys(db, cipher)
        assert private_1
        assert public_1

        # 2回目の呼び出しでは同じ鍵が返る（再生成されない）
        private_2, public_2 = await app_config_service.get_or_create_vapid_keys(db, cipher)
        assert private_1 == private_2
        assert public_1 == public_2

        assert await app_config_service.get_vapid_public_key(db) == public_1
