"""VRChatログインセッション(vrchat_session)の保存・取得・失効。

単一ユーザー前提のため、常に高々1行のみを有効なセッションとして扱う。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecretCipher
from app.models.vrchat_session import VRChatSession


async def get_active_session(db: AsyncSession) -> VRChatSession | None:
    result = await db.execute(
        select(VRChatSession).where(VRChatSession.is_valid.is_(True)).order_by(
            VRChatSession.obtained_at.desc()
        )
    )
    return result.scalars().first()


async def save_session(
    db: AsyncSession,
    cipher: SecretCipher,
    *,
    vrchat_user_id: str,
    vrchat_display_name: str,
    auth_cookie: str,
    two_factor_cookie: str | None,
) -> VRChatSession:
    # 単一ユーザー前提のため、既存の有効セッションは無効化してから新規作成する。
    existing = await db.execute(select(VRChatSession).where(VRChatSession.is_valid.is_(True)))
    for row in existing.scalars().all():
        row.is_valid = False

    two_factor_encrypted = cipher.encrypt(two_factor_cookie) if two_factor_cookie else None
    session = VRChatSession(
        vrchat_user_id=vrchat_user_id,
        vrchat_display_name=vrchat_display_name,
        auth_cookie_encrypted=cipher.encrypt(auth_cookie),
        two_factor_cookie_encrypted=two_factor_encrypted,
        is_valid=True,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_decrypted_cookies(
    db: AsyncSession, cipher: SecretCipher
) -> tuple[str, str | None] | None:
    """(auth_cookie, two_factor_cookie) を復号して返す。有効なセッションがなければNone。"""
    session = await get_active_session(db)
    if session is None:
        return None
    auth_cookie = cipher.decrypt(session.auth_cookie_encrypted)
    two_factor_cookie = (
        cipher.decrypt(session.two_factor_cookie_encrypted)
        if session.two_factor_cookie_encrypted
        else None
    )
    return auth_cookie, two_factor_cookie


async def mark_invalid(db: AsyncSession) -> None:
    result = await db.execute(select(VRChatSession).where(VRChatSession.is_valid.is_(True)))
    for row in result.scalars().all():
        row.is_valid = False
    await db.commit()


async def touch_last_validated(db: AsyncSession, session: VRChatSession) -> None:
    session.last_validated_at = datetime.now(UTC)
    await db.commit()
