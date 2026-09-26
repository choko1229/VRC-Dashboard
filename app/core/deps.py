"""ルーター共通のFastAPI依存関係。"""

from __future__ import annotations

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import SecretCipher, get_secret_cipher
from app.db.session import get_db
from app.models.dashboard_user import DashboardUser
from app.services import auth_service, game_log_agent_token_service, vrchat_session_service
from app.services.session_service import get_user_for_session_token


class NotAuthenticatedError(Exception):
    """未ログイン、またはセッションが無効/失効している。"""


class NotAdminError(Exception):
    """管理者権限が必要な操作を非管理者が行おうとした。"""


class VRChatLoginRequiredError(Exception):
    """ログイン中のダッシュボードユーザーが、まだ自分のVRChatアカウントでログインしていない
    （またはVRChatのセッションが失効している）。"""


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
    # 許可リストから外されたユーザーは、セッションが残っていても（削除画面以外の経路で
    # 外された場合も含めて）即座に締め出す。
    if not await auth_service.is_allowlisted(db, user.discord_user_id):
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


async def get_current_vrchat_user(
    current_user: DashboardUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardUser:
    """自分のVRChatアカウントでログイン済みのダッシュボードユーザーを取得する。

    複数人利用のため、フレンド・アバター等のVRChat由来のデータはDiscordアカウント
    （ダッシュボードユーザー）ごとに、そのユーザー自身のVRChatアカウントから取得する。
    未ログイン/セッション失効時はVRChatLoginRequiredErrorを送出し、app.main側で
    VRChatログイン画面（/settings/vrchat）へのリダイレクトに変換される。
    """
    session = await vrchat_session_service.get_active_session(db, current_user.id)
    if session is None:
        raise VRChatLoginRequiredError
    return current_user


def get_cipher(settings: Settings = Depends(get_settings)) -> SecretCipher:
    return get_secret_cipher(settings)


async def require_game_log_api_key(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> int:
    """デスクトップエージェントからのゲームログ取り込みを`Authorization: Bearer <token>`で認証する。

    トークンはブラウザでのペアリング（device_auth_service）またはgame_log_agent_token_service
    で発行された、複数デバイスに対応するトークンのいずれか。戻り値はトークンの所有者
    （ペアリングを承認したダッシュボードユーザー）のID。
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise InvalidGameLogApiKeyError
    raw_token = authorization.removeprefix("Bearer ").strip()
    if not raw_token:
        raise InvalidGameLogApiKeyError
    owner_id = await game_log_agent_token_service.verify_token(db, raw_token)
    if owner_id is None:
        raise InvalidGameLogApiKeyError
    owner = await db.get(DashboardUser, owner_id)
    if owner is None or not await auth_service.is_allowlisted(db, owner.discord_user_id):
        raise InvalidGameLogApiKeyError
    return owner_id
