"""許可リスト照合・ダッシュボードユーザーのUpsertを担う。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
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


async def allowlist_is_empty(db: AsyncSession) -> bool:
    """許可リストが1件も登録されていないか（初回起動時のブートストラップ判定用）。"""
    result = await db.execute(select(func.count()).select_from(DiscordAllowlistEntry))
    return result.scalar_one() == 0


async def bootstrap_first_admin(db: AsyncSession, discord_user_id: str, *, label: str) -> None:
    """許可リストが空の状態で最初にログインしたユーザーを許可リストへ自動登録する。

    呼び出し側は事前に `allowlist_is_empty` がTrueであることを確認しておくこと。
    """
    db.add(
        DiscordAllowlistEntry(
            discord_user_id=discord_user_id,
            label=label,
            note="初回ログインにより自動登録された管理者",
        )
    )
    await db.commit()


async def upsert_dashboard_user(
    db: AsyncSession, discord_user: DiscordUser, *, is_admin: bool = False
) -> DashboardUser:
    """許可リスト確認済みのDiscordユーザー情報でdashboard_userを作成/更新する。

    呼び出し側は事前に `is_allowlisted` を確認しておくこと
    （ここでは許可リストチェックは行わない）。
    `is_admin` は新規作成時のみ適用され、既存ユーザーの権限を上書きすることはない
    （再ログインのたびに管理者権限が変動しないようにするため）。
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
            is_admin=is_admin,
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
