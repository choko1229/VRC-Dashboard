"""VRChatログインセッション(vrchat_session)の保存・取得・失効。

複数人利用に対応するため、ダッシュボードユーザー（Discordアカウント）ごとに高々1行を
有効なセッションとして扱う（各ユーザーが自分のVRChatアカウントでログインする）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecretCipher
from app.models.dashboard_user import DashboardUser
from app.models.discord_allowlist_entry import DiscordAllowlistEntry
from app.models.vrchat_session import VRChatSession
from app.services import app_config_service
from app.services.vrchat.client import VRChatClient


async def get_active_session(db: AsyncSession, user_id: int) -> VRChatSession | None:
    result = await db.execute(
        select(VRChatSession)
        .where(VRChatSession.dashboard_user_id == user_id, VRChatSession.is_valid.is_(True))
        .order_by(VRChatSession.obtained_at.desc())
    )
    return result.scalars().first()


async def list_user_ids_with_active_session(db: AsyncSession) -> list[int]:
    """有効なVRChatセッションを持つダッシュボードユーザーID一覧（起動時のPipeline一斉起動用）。

    許可リストから外されたユーザーは除く。
    """
    result = await db.execute(
        select(VRChatSession.dashboard_user_id)
        .join(DashboardUser, VRChatSession.dashboard_user_id == DashboardUser.id)
        .join(
            DiscordAllowlistEntry,
            DiscordAllowlistEntry.discord_user_id == DashboardUser.discord_user_id,
        )
        .where(VRChatSession.is_valid.is_(True))
        .distinct()
    )
    return list(result.scalars().all())


async def find_other_user_with_vrchat_account(
    db: AsyncSession, user_id: int, vrchat_user_id: str
) -> int | None:
    """同じVRChatアカウントで既にログイン中の、別のダッシュボードユーザーのIDを返す。

    1つのVRChatアカウントのデータ（フレンド・通知等）が複数のダッシュボードユーザーに
    重複して取り込まれないよう、ログイン時に拒否するために使う。
    """
    result = await db.execute(
        select(VRChatSession.dashboard_user_id).where(
            VRChatSession.vrchat_user_id == vrchat_user_id,
            VRChatSession.dashboard_user_id != user_id,
            VRChatSession.is_valid.is_(True),
        )
    )
    return result.scalars().first()


async def save_session(
    db: AsyncSession,
    cipher: SecretCipher,
    user_id: int,
    *,
    vrchat_user_id: str,
    vrchat_display_name: str,
    auth_cookie: str,
    two_factor_cookie: str | None,
) -> VRChatSession:
    # 有効なセッションはユーザーごとに1つのため、そのユーザーの既存セッションを無効化してから作る。
    existing = await db.execute(
        select(VRChatSession).where(
            VRChatSession.dashboard_user_id == user_id, VRChatSession.is_valid.is_(True)
        )
    )
    for row in existing.scalars().all():
        row.is_valid = False

    two_factor_encrypted = cipher.encrypt(two_factor_cookie) if two_factor_cookie else None
    session = VRChatSession(
        dashboard_user_id=user_id,
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
    db: AsyncSession, cipher: SecretCipher, user_id: int
) -> tuple[str, str | None] | None:
    """(auth_cookie, two_factor_cookie) を復号して返す。有効なセッションがなければNone。"""
    session = await get_active_session(db, user_id)
    if session is None:
        return None
    auth_cookie = cipher.decrypt(session.auth_cookie_encrypted)
    two_factor_cookie = (
        cipher.decrypt(session.two_factor_cookie_encrypted)
        if session.two_factor_cookie_encrypted
        else None
    )
    return auth_cookie, two_factor_cookie


async def build_client(
    db: AsyncSession, cipher: SecretCipher, user_id: int
) -> VRChatClient | None:
    """保存済みのVRChatセッションからAPIクライアントを組み立てる。未連携ならNone。

    呼び出し側は必ずtry/finallyで`close()`すること。
    """
    cookies = await get_decrypted_cookies(db, cipher, user_id)
    if cookies is None:
        return None
    auth_cookie, two_factor_cookie = cookies
    user_agent = await app_config_service.get_vrchat_user_agent(db)
    return VRChatClient(
        user_agent=user_agent, auth_cookie=auth_cookie, two_factor_cookie=two_factor_cookie
    )


async def mark_invalid(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(
        select(VRChatSession).where(
            VRChatSession.dashboard_user_id == user_id, VRChatSession.is_valid.is_(True)
        )
    )
    for row in result.scalars().all():
        row.is_valid = False
    await db.commit()


async def touch_last_validated(db: AsyncSession, session: VRChatSession) -> None:
    session.last_validated_at = datetime.now(UTC)
    await db.commit()


async def update_self_location(
    db: AsyncSession,
    user_id: int,
    *,
    location: str | None,
    world_id: str | None,
    world_name: str | None,
) -> None:
    """Pipelineの"user-location"イベントで、自分（操作者）自身の現在地を更新する。

    サイドバーの「同じインスタンス」判定に使う（app.services.friends_service参照）。
    """
    session = await get_active_session(db, user_id)
    if session is None:
        return
    session.self_location = location
    session.self_world_id = world_id
    session.self_world_name = world_name
    await db.commit()
