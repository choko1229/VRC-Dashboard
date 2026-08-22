"""app_settingに保存された設定から通知送信手段を組み立てる。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecretCipher
from app.notifications.discord_sender import DiscordNotifySender
from app.services import app_setting_service

_DISCORD_BOT_URL_KEY = "discord_notify_bot_url"
_DISCORD_SHARED_SECRET_KEY = "discord_notify_shared_secret_encrypted"


async def build_discord_sender(db: AsyncSession, cipher: SecretCipher) -> DiscordNotifySender:
    bot_url = await app_setting_service.get_setting(db, _DISCORD_BOT_URL_KEY) or ""
    encrypted_secret = await app_setting_service.get_setting(db, _DISCORD_SHARED_SECRET_KEY)
    shared_secret = cipher.decrypt(encrypted_secret) if encrypted_secret else ""
    return DiscordNotifySender(bot_url=bot_url, shared_secret=shared_secret)


async def get_discord_notify_config(
    db: AsyncSession, cipher: SecretCipher
) -> tuple[str, bool]:
    """(bot_url, シークレット設定済みか) を返す。シークレット自体は画面に出さない。"""
    bot_url = await app_setting_service.get_setting(db, _DISCORD_BOT_URL_KEY) or ""
    encrypted_secret = await app_setting_service.get_setting(db, _DISCORD_SHARED_SECRET_KEY)
    return bot_url, encrypted_secret is not None


async def set_discord_notify_config(
    db: AsyncSession, cipher: SecretCipher, *, bot_url: str, shared_secret: str
) -> None:
    await app_setting_service.set_setting(db, _DISCORD_BOT_URL_KEY, bot_url)
    if shared_secret:
        encrypted = cipher.encrypt(shared_secret)
        await app_setting_service.set_setting(db, _DISCORD_SHARED_SECRET_KEY, encrypted)
