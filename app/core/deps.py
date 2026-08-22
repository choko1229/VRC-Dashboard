"""ルーター共通のFastAPI依存関係。"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import SecretCipher, get_secret_cipher
from app.db.session import get_db
from app.models.dashboard_user import DashboardUser
from app.services.session_service import get_user_for_session_token


class NotAuthenticatedError(Exception):
    """未ログイン、またはセッションが無効/失効している。"""


class NotAdminError(Exception):
    """管理者権限が必要な操作を非管理者が行おうとした。"""


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DashboardUser:
    """ログイン中のダッシュボードユーザーを取得する。未ログインならNotAuthenticatedErrorを送出する。

    このエラーはapp.main側でRedirectResponse(/login)に変換される。
    """
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token is None:
        raise NotAuthenticatedError

    user = await get_user_for_session_token(db, raw_token)
    if user is None:
        raise NotAuthenticatedError

    # テンプレート側（partials/nav.html）で管理者向けリンクの出し分けに使う。
    request.state.dashboard_user = user
    return user


async def get_current_admin_user(
    current_user: DashboardUser = Depends(get_current_user),
) -> DashboardUser:
    """管理者権限を持つダッシュボードユーザーを取得する。非管理者ならNotAdminErrorを送出する。"""
    if not current_user.is_admin:
        raise NotAdminError
    return current_user


def get_cipher(settings: Settings = Depends(get_settings)) -> SecretCipher:
    return get_secret_cipher(settings)
