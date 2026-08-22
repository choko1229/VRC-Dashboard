"""ダッシュボードのサーバーサイドセッションの発行・検証・失効。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_session_token, hash_session_token
from app.models.dashboard_session import DashboardSession
from app.models.dashboard_user import DashboardUser


async def create_session(
    db: AsyncSession,
    *,
    dashboard_user_id: int,
    ttl_seconds: int,
    user_agent: str | None,
    ip_address: str | None,
) -> str:
    """新規セッションを発行し、Cookieに載せる生トークンを返す。"""
    raw_token = generate_session_token()
    session = DashboardSession(
        token_hash=hash_session_token(raw_token),
        dashboard_user_id=dashboard_user_id,
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(session)
    await db.commit()
    return raw_token


async def get_user_for_session_token(db: AsyncSession, raw_token: str) -> DashboardUser | None:
    """Cookieの生トークンから有効なセッションを検証し、紐づくユーザーを返す。"""
    token_hash = hash_session_token(raw_token)
    result = await db.execute(
        select(DashboardSession).where(DashboardSession.token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    if session.revoked_at is not None:
        return None
    if session.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        return None

    session.last_seen_at = datetime.now(UTC)
    user = await db.get(DashboardUser, session.dashboard_user_id)
    await db.commit()
    return user


async def revoke_session(db: AsyncSession, raw_token: str) -> None:
    token_hash = hash_session_token(raw_token)
    result = await db.execute(
        select(DashboardSession).where(DashboardSession.token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        await db.commit()
