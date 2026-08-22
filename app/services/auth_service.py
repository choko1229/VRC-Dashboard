"""許可リスト照合・ダッシュボードユーザーのUpsertを担う。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard_user import DashboardUser
from app.models.discord_allowlist_entry import DiscordAllowlistEntry
from app.schemas.discord import DiscordUser


class NotAllowlistedError(Exception):
    """許可リストに含まれていないDiscordユーザーがログインを試みた。"""


async def is_allowlisted(db: AsyncSession, discord_user_id: str) -> bool:
    result = await db.execute(
        select(DiscordAllowlistEntry).where(
            DiscordAllowlistEntry.discord_user_id == discord_user_id
        )
    )
    return result.scalar_one_or_none() is not None


async def upsert_dashboard_user(db: AsyncSession, discord_user: DiscordUser) -> DashboardUser:
    """許可リスト確認済みのDiscordユーザー情報でdashboard_userを作成/更新する。

    呼び出し側は事前に `is_allowlisted` を確認しておくこと
    （ここでは許可リストチェックは行わない）。
    """
    result = await db.execute(
        select(DashboardUser).where(DashboardUser.discord_user_id == discord_user.id)
    )
    user = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if user is None:
        user = DashboardUser(
            discord_user_id=discord_user.id,
            discord_username=discord_user.username,
            discord_global_name=discord_user.global_name,
            discord_avatar_hash=discord_user.avatar,
            first_login_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.discord_username = discord_user.username
        user.discord_global_name = discord_user.global_name
        user.discord_avatar_hash = discord_user.avatar
        user.last_login_at = now

    await db.commit()
    await db.refresh(user)
    return user
