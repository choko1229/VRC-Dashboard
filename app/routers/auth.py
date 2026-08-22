"""Discord OAuth2によるダッシュボードログイン。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import get_cipher
from app.core.security import SecretCipher, generate_oauth_state
from app.core.templating import templates
from app.db.session import get_db
from app.services import app_config_service, auth_service, session_service
from app.services.discord_oauth_service import (
    DiscordOAuthError,
    build_authorize_url,
    exchange_code_for_token,
    fetch_current_discord_user,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_OAUTH_STATE_COOKIE = "oauth_state"


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_page(
    request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse | RedirectResponse:
    if not await app_config_service.is_discord_oauth_configured(db):
        return RedirectResponse(url="/setup", status_code=302)
    return templates.TemplateResponse(request, "auth/login.html")


@router.get("/auth/discord/login", response_model=None)
async def discord_login(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    client_id, _ = await app_config_service.get_discord_oauth_config(db, cipher)
    if not client_id:
        return RedirectResponse(url="/setup", status_code=302)

    state = generate_oauth_state()
    redirect_uri = str(request.url_for("discord_callback"))
    authorize_url = build_authorize_url(client_id=client_id, redirect_uri=redirect_uri, state=state)

    response = RedirectResponse(url=authorize_url, status_code=302)
    response.set_cookie(
        _OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.app_env != "development",
    )
    return response


@router.get("/auth/discord/callback", response_class=HTMLResponse, response_model=None)
async def discord_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse | RedirectResponse:
    expected_state = request.cookies.get(_OAUTH_STATE_COOKIE)

    if error is not None:
        logger.info("Discord OAuth2がユーザーによって拒否されました: %s", error)
        return templates.TemplateResponse(
            request, "auth/denied.html", {"reason": "Discordでの認可がキャンセルされました。"}
        )

    if code is None or state is None or expected_state is None or state != expected_state:
        logger.warning("Discord OAuth2のstate検証に失敗しました")
        return templates.TemplateResponse(
            request,
            "auth/denied.html",
            {"reason": "認証セッションが無効です。もう一度ログインし直してください。"},
            status_code=400,
        )

    client_id, client_secret = await app_config_service.get_discord_oauth_config(db, cipher)
    redirect_uri = str(request.url_for("discord_callback"))

    try:
        token = await exchange_code_for_token(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
        discord_user = await fetch_current_discord_user(access_token=token.access_token)
    except DiscordOAuthError:
        return templates.TemplateResponse(
            request,
            "auth/denied.html",
            {"reason": "Discordとの通信に失敗しました。時間を置いて再度お試しください。"},
            status_code=502,
        )

    is_bootstrap = await auth_service.allowlist_is_empty(db)
    if is_bootstrap:
        # 許可リストが空＝まだ誰もログインしたことがない初回起動状態。
        # このユーザーを管理者として自動登録し、許可リストのセットアップ待ちを解消する。
        await auth_service.bootstrap_first_admin(
            db, discord_user.id, label=discord_user.global_name or discord_user.username
        )
        logger.info("初回ログインのため管理者として自動登録しました: %s", discord_user.id)
    elif not await auth_service.is_allowlisted(db, discord_user.id):
        logger.info("許可リスト外のDiscordユーザーのログイン試行: %s", discord_user.id)
        response = templates.TemplateResponse(
            request,
            "auth/denied.html",
            {"reason": "このDiscordアカウントには利用権限がありません。"},
            status_code=403,
        )
        response.delete_cookie(_OAUTH_STATE_COOKIE)
        return response

    user = await auth_service.upsert_dashboard_user(db, discord_user, is_admin=is_bootstrap)
    raw_session_token = await session_service.create_session(
        db,
        dashboard_user_id=user.id,
        ttl_seconds=settings.session_ttl_seconds,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )

    redirect_response = RedirectResponse(url="/", status_code=302)
    redirect_response.delete_cookie(_OAUTH_STATE_COOKIE)
    redirect_response.set_cookie(
        settings.session_cookie_name,
        raw_session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.app_env != "development",
    )
    return redirect_response


@router.post("/auth/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token is not None:
        await session_service.revoke_session(db, raw_token)

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(settings.session_cookie_name)
    return response
