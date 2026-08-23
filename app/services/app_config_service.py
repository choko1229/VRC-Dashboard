"""外部連携設定（Discord OAuthアプリ・VRChat API連絡先・VAPID鍵）のDB管理。

.envは起動に必要な最小限（ポート等）のみとし、これらは初回セットアップ画面・
設定画面から入力してもらい、app_settingテーブルに保存する
（秘密情報はSecretCipherでアプリ層暗号化してから保存する）。
"""

from __future__ import annotations

import base64
import secrets

from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecretCipher, hash_session_token
from app.services import app_setting_service

_DISCORD_CLIENT_ID_KEY = "discord_oauth_client_id"
_DISCORD_CLIENT_SECRET_KEY = "discord_oauth_client_secret_encrypted"

_VRCHAT_USER_AGENT_KEY = "vrchat_api_user_agent"
_DEFAULT_VRCHAT_USER_AGENT = "VRC-Dashboard/1.0"

_VAPID_PRIVATE_KEY_KEY = "vapid_private_key_encrypted"
_VAPID_PUBLIC_KEY_KEY = "vapid_public_key"
_VAPID_CONTACT_EMAIL_KEY = "vapid_contact_email"
_DEFAULT_VAPID_CONTACT_EMAIL = "mailto:example@example.com"


async def is_discord_oauth_configured(db: AsyncSession) -> bool:
    client_id = await app_setting_service.get_setting(db, _DISCORD_CLIENT_ID_KEY)
    return bool(client_id)


async def get_discord_oauth_config(db: AsyncSession, cipher: SecretCipher) -> tuple[str, str]:
    """(client_id, client_secret) を返す。未設定の場合は空文字。"""
    client_id = await app_setting_service.get_setting(db, _DISCORD_CLIENT_ID_KEY) or ""
    encrypted_secret = await app_setting_service.get_setting(db, _DISCORD_CLIENT_SECRET_KEY)
    client_secret = cipher.decrypt(encrypted_secret) if encrypted_secret else ""
    return client_id, client_secret


async def set_discord_oauth_config(
    db: AsyncSession, cipher: SecretCipher, *, client_id: str, client_secret: str
) -> None:
    await app_setting_service.set_setting(db, _DISCORD_CLIENT_ID_KEY, client_id)
    if client_secret:
        await app_setting_service.set_setting(
            db, _DISCORD_CLIENT_SECRET_KEY, cipher.encrypt(client_secret)
        )


async def get_vrchat_user_agent(db: AsyncSession) -> str:
    return await app_setting_service.get_setting(db, _VRCHAT_USER_AGENT_KEY) or (
        _DEFAULT_VRCHAT_USER_AGENT
    )


async def set_vrchat_user_agent(db: AsyncSession, value: str) -> None:
    await app_setting_service.set_setting(db, _VRCHAT_USER_AGENT_KEY, value or None)


def _generate_vapid_keypair() -> tuple[str, str]:
    """(private_key, public_key) をbase64url(パディングなし)のraw鍵として生成する。

    private_key: 32byteの生の秘密鍵（pywebpushのVapid.from_string()が要求する形式）
    public_key: 65byteの非圧縮公開鍵（ブラウザのapplicationServerKeyに使う形式）
    """

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_numbers = private_key.private_numbers()
    private_raw = private_numbers.private_value.to_bytes(32, "big")

    public_numbers = private_key.public_key().public_numbers()
    public_raw = (
        b"\x04" + public_numbers.x.to_bytes(32, "big") + public_numbers.y.to_bytes(32, "big")
    )
    return b64url(private_raw), b64url(public_raw)


async def get_or_create_vapid_keys(db: AsyncSession, cipher: SecretCipher) -> tuple[str, str]:
    """(private_key, public_key) を返す。未生成であれば自動生成してDBへ保存する。"""
    encrypted_private = await app_setting_service.get_setting(db, _VAPID_PRIVATE_KEY_KEY)
    public_key = await app_setting_service.get_setting(db, _VAPID_PUBLIC_KEY_KEY)

    if encrypted_private and public_key:
        return cipher.decrypt(encrypted_private), public_key

    private_key, public_key = _generate_vapid_keypair()
    await app_setting_service.set_setting(
        db, _VAPID_PRIVATE_KEY_KEY, cipher.encrypt(private_key)
    )
    await app_setting_service.set_setting(db, _VAPID_PUBLIC_KEY_KEY, public_key)
    return private_key, public_key


async def get_vapid_public_key(db: AsyncSession) -> str | None:
    return await app_setting_service.get_setting(db, _VAPID_PUBLIC_KEY_KEY)


async def get_vapid_contact_email(db: AsyncSession) -> str:
    return await app_setting_service.get_setting(db, _VAPID_CONTACT_EMAIL_KEY) or (
        _DEFAULT_VAPID_CONTACT_EMAIL
    )


async def set_vapid_contact_email(db: AsyncSession, value: str) -> None:
    await app_setting_service.set_setting(db, _VAPID_CONTACT_EMAIL_KEY, value or None)


_GAME_LOG_API_KEY_HASH_KEY = "game_log_api_key_hash"


async def is_game_log_api_key_configured(db: AsyncSession) -> bool:
    return bool(await app_setting_service.get_setting(db, _GAME_LOG_API_KEY_HASH_KEY))


async def generate_game_log_api_key(db: AsyncSession) -> str:
    """新しいAPIキーを発行する（既存キーは無効化される）。生の値は画面表示の一度きりで、DBにはハッシュのみ保存する。"""
    raw_key = secrets.token_urlsafe(32)
    await app_setting_service.set_setting(
        db, _GAME_LOG_API_KEY_HASH_KEY, hash_session_token(raw_key)
    )
    return raw_key


async def revoke_game_log_api_key(db: AsyncSession) -> None:
    await app_setting_service.set_setting(db, _GAME_LOG_API_KEY_HASH_KEY, None)


async def verify_game_log_api_key(db: AsyncSession, raw_key: str) -> bool:
    stored_hash = await app_setting_service.get_setting(db, _GAME_LOG_API_KEY_HASH_KEY)
    if not stored_hash:
        return False
    return secrets.compare_digest(stored_hash, hash_session_token(raw_key))


_GAME_LOG_AGENT_VERSION_KEY = "game_log_agent_version"


async def get_game_log_agent_version(db: AsyncSession) -> str | None:
    return await app_setting_service.get_setting(db, _GAME_LOG_AGENT_VERSION_KEY)


async def set_game_log_agent_version(db: AsyncSession, version: str) -> None:
    await app_setting_service.set_setting(db, _GAME_LOG_AGENT_VERSION_KEY, version)
