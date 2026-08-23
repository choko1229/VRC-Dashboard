"""ルーター共通のFastAPI依存関係。"""

from __future__ import annotations

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import SecretCipher, get_secret_cipher
from app.db.session import get_db
from app.models.dashboard_user import DashboardUser
from app.services import app_config_service
from app.services.session_service import get_user_for_session_token


class NotAuthenticatedError(Exception):
    """未ログイン、またはセッションが無効/失効している。"""


class NotAdminError(Exception):
    """管理者権限が必要な操作を非管理者が行おうとした。"""


class InvalidGameLogApiKeyError(Exception):
    """ゲームログ取り込みAPIキーが未設定/不正。"""


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


async def require_game_log_api_key(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> None:
    """ローカルエージェントからのゲームログ取り込みを`Authorization: Bearer <key>`で認証する。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise InvalidGameLogApiKeyError
    raw_key = authorization.removeprefix("Bearer ").strip()
    if not raw_key or not await app_config_service.verify_game_log_api_key(db, raw_key):
        raise InvalidGameLogApiKeyError


async def require_admin_or_release_token(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """新しいエージェントビルドのアップロードを認証する。

    ビルドスクリプトからの自動アップロード（`Authorization: Bearer <リリーストークン>`）と、
    管理画面からの手動アップロード（ログインセッションCookie、管理者のみ）の両方を許可する。
    """
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.removeprefix("Bearer ").strip()
        if raw_token and await app_config_service.verify_release_upload_token(db, raw_token):
            return
        raise InvalidGameLogApiKeyError

    raw_session_token = request.cookies.get(settings.session_cookie_name)
    if raw_session_token is None:
        raise NotAuthenticatedError
    user = await get_user_for_session_token(db, raw_session_token)
    if user is None:
        raise NotAuthenticatedError
    if not user.is_admin:
        raise NotAdminError
