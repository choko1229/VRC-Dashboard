"""フェーズ5: Discord通知設定(app_setting経由)のユニットテスト。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import SecretCipher
from app.services import notification_service

_TEST_FERNET_KEY = "gdsF_NX-iLtl8QLOwmQyFeEdQtOmWXiAlHD4kTrLuh4="


async def test_set_and_get_discord_notify_config(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    async with db_session_factory() as db:
        bot_url, secret_configured = await notification_service.get_discord_notify_config(
            db, cipher
        )
        assert bot_url == ""
        assert secret_configured is False

        await notification_service.set_discord_notify_config(
            db, cipher, bot_url="https://bot.example.com", shared_secret="s3cr3t"
        )
        bot_url, secret_configured = await notification_service.get_discord_notify_config(
            db, cipher
        )
        assert bot_url == "https://bot.example.com"
        assert secret_configured is True

        sender = await notification_service.build_discord_sender(db, cipher)
        assert sender is not None


async def test_blank_shared_secret_does_not_clear_existing(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    async with db_session_factory() as db:
        await notification_service.set_discord_notify_config(
            db, cipher, bot_url="https://bot.example.com", shared_secret="s3cr3t"
        )
        # シークレット欄を空で再送信しても、既存のシークレットは維持される
        await notification_service.set_discord_notify_config(
            db, cipher, bot_url="https://bot2.example.com", shared_secret=""
        )
        bot_url, secret_configured = await notification_service.get_discord_notify_config(
            db, cipher
        )
        assert bot_url == "https://bot2.example.com"
        assert secret_configured is True
