"""設定画面。許可リスト管理・VRChatアカウント連携。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import get_cipher, get_current_admin_user, get_current_user
from app.core.security import SecretCipher
from app.core.templating import templates
from app.db.session import get_db
from app.models.dashboard_user import DashboardUser
from app.models.discord_allowlist_entry import DiscordAllowlistEntry
from app.schemas.vrchat import VRChatUser
from app.services import (
    app_config_service,
    notification_service,
    vrchat_session_service,
    vrchat_sync_service,
)
from app.services.vrchat.client import (
    TwoFactorMethod,
    TwoFactorRequired,
    VRChatAPIError,
    VRChatAuthError,
    VRChatClient,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", dependencies=[Depends(get_current_user)])

_PENDING_AUTH_COOKIE = "vrchat_pending_auth"


async def _render_allowlist_fragment(request: Request, db: AsyncSession) -> HTMLResponse:
    result = await db.execute(
        select(DiscordAllowlistEntry).order_by(DiscordAllowlistEntry.created_at)
    )
    entries = result.scalars().all()
    return templates.TemplateResponse(
        request, "settings/_allowlist_list.html", {"entries": entries}
    )


@router.get("/allowlist", response_class=HTMLResponse)
async def allowlist_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: DashboardUser = Depends(get_current_admin_user),
) -> HTMLResponse:
    result = await db.execute(
        select(DiscordAllowlistEntry).order_by(DiscordAllowlistEntry.created_at)
    )
    entries = result.scalars().all()
    return templates.TemplateResponse(request, "settings/allowlist.html", {"entries": entries})


@router.post("/allowlist", response_class=HTMLResponse)
async def add_allowlist_entry(
    request: Request,
    discord_user_id: str = Form(...),
    label: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    admin: DashboardUser = Depends(get_current_admin_user),
) -> HTMLResponse:
    existing = await db.execute(
        select(DiscordAllowlistEntry).where(
            DiscordAllowlistEntry.discord_user_id == discord_user_id
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(DiscordAllowlistEntry(discord_user_id=discord_user_id, label=label or None))
        await db.commit()
    return await _render_allowlist_fragment(request, db)


@router.delete("/allowlist/{entry_id}", response_class=HTMLResponse)
async def delete_allowlist_entry(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    admin: DashboardUser = Depends(get_current_admin_user),
) -> HTMLResponse:
    entry = await db.get(DiscordAllowlistEntry, entry_id)
    if entry is not None:
        await db.delete(entry)
        await db.commit()
    return await _render_allowlist_fragment(request, db)


def _panel_response(
    request: Request, *, status_code: int = 200, **context: object
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "settings/_vrchat_panel.html", context, status_code=status_code
    )


async def _finalize_vrchat_login(
    request: Request,
    db: AsyncSession,
    cipher: SecretCipher,
    client: VRChatClient,
    user: VRChatUser,
) -> HTMLResponse:
    """ログイン/2FA確定後の共通処理: セッション保存→初回フレンド同期→Pipeline起動。"""
    await vrchat_session_service.save_session(
        db,
        cipher,
        vrchat_user_id=user.id,
        vrchat_display_name=user.display_name,
        auth_cookie=client.auth_cookie or "",
        two_factor_cookie=client.two_factor_cookie,
    )

    try:
        await vrchat_sync_service.full_friends_sync(db, client)
    except VRChatAPIError:
        logger.warning("ログイン直後のフレンド初回同期に失敗しました。/friends/syncで再試行できます。")

    request.app.state.pipeline_manager.start()

    return _panel_response(request, mode="connected", display_name=user.display_name)


@router.get("/vrchat", response_class=HTMLResponse)
async def vrchat_settings_page(
    request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    session = await vrchat_session_service.get_active_session(db)
    mode = "connected" if session is not None else "disconnected"
    return templates.TemplateResponse(
        request,
        "settings/vrchat.html",
        {"mode": mode, "display_name": session.vrchat_display_name if session else None},
    )


@router.post("/vrchat/login", response_class=HTMLResponse, response_model=None)
async def vrchat_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    user_agent = await app_config_service.get_vrchat_user_agent(db)
    client = VRChatClient(user_agent=user_agent)
    try:
        user = await client.login(username, password)
    except TwoFactorRequired as exc:
        response = _panel_response(request, mode="pending_2fa", methods=exc.methods)
        if client.auth_cookie:
            response.set_cookie(
                _PENDING_AUTH_COOKIE,
                client.auth_cookie,
                max_age=600,
                httponly=True,
                samesite="lax",
                secure=settings.app_env != "development",
            )
        await client.close()
        return response
    except VRChatAuthError:
        await client.close()
        return _panel_response(
            request,
            status_code=401,
            mode="disconnected",
            error_message="ユーザー名またはパスワードが正しくありません。",
        )
    except VRChatAPIError:
        await client.close()
        return _panel_response(
            request,
            status_code=502,
            mode="disconnected",
            error_message="VRChatとの通信に失敗しました。時間を置いて再度お試しください。",
        )

    response = await _finalize_vrchat_login(request, db, cipher, client, user)
    await client.close()
    return response


@router.post("/vrchat/verify-2fa", response_class=HTMLResponse)
async def vrchat_verify_2fa(
    request: Request,
    method: str = Form(...),
    code: str = Form(...),
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    pending_auth_cookie = request.cookies.get(_PENDING_AUTH_COOKIE)
    if not pending_auth_cookie:
        return _panel_response(
            request,
            status_code=400,
            mode="disconnected",
            error_message="ログイン情報の有効期限が切れました。もう一度ログインしてください。",
        )

    two_factor_method: TwoFactorMethod = "totp" if method == "totp" else "emailOtp"
    user_agent = await app_config_service.get_vrchat_user_agent(db)
    client = VRChatClient(user_agent=user_agent, auth_cookie=pending_auth_cookie)
    try:
        await client.verify_two_factor(two_factor_method, code)
        user = await client.get_current_user()
    except (VRChatAuthError, VRChatAPIError):
        await client.close()
        return _panel_response(
            request,
            status_code=401,
            mode="pending_2fa",
            methods=[method],
            error_message="2段階認証コードが正しくないか、通信に失敗しました。",
        )

    response = await _finalize_vrchat_login(request, db, cipher, client, user)
    response.delete_cookie(_PENDING_AUTH_COOKIE)
    await client.close()
    return response


@router.post("/vrchat/logout", response_class=HTMLResponse)
async def vrchat_logout(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    await vrchat_session_service.mark_invalid(db)
    await request.app.state.pipeline_manager.stop()
    return _panel_response(request, mode="disconnected")


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    bot_url, secret_configured = await notification_service.get_discord_notify_config(db, cipher)
    # VAPID鍵は未生成なら自動生成する（ユーザーが意識する必要はない）。
    await app_config_service.get_or_create_vapid_keys(db, cipher)
    return templates.TemplateResponse(
        request,
        "settings/notifications.html",
        {"bot_url": bot_url, "secret_configured": secret_configured},
    )


@router.post("/notifications/discord", response_class=HTMLResponse)
async def update_discord_notify_config(
    request: Request,
    bot_url: str = Form(""),
    shared_secret: str = Form(""),
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    await notification_service.set_discord_notify_config(
        db, cipher, bot_url=bot_url, shared_secret=shared_secret
    )
    _, secret_configured = await notification_service.get_discord_notify_config(db, cipher)
    return templates.TemplateResponse(
        request,
        "settings/_discord_notify_form.html",
        {"bot_url": bot_url, "secret_configured": secret_configured, "saved": True},
    )


@router.get("/general", response_class=HTMLResponse)
async def general_settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    client_id, _ = await app_config_service.get_discord_oauth_config(db, cipher)
    vrchat_user_agent = await app_config_service.get_vrchat_user_agent(db)
    redirect_uri = str(request.url_for("discord_callback"))
    return templates.TemplateResponse(
        request,
        "settings/general.html",
        {
            "client_id": client_id,
            "vrchat_user_agent": vrchat_user_agent,
            "redirect_uri": redirect_uri,
        },
    )


@router.post("/general/discord-oauth", response_class=HTMLResponse)
async def update_discord_oauth_config(
    request: Request,
    client_id: str = Form(...),
    client_secret: str = Form(""),
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse:
    await app_config_service.set_discord_oauth_config(
        db, cipher, client_id=client_id, client_secret=client_secret
    )
    return templates.TemplateResponse(
        request,
        "settings/_discord_oauth_form.html",
        {"client_id": client_id, "saved": True},
    )


@router.post("/general/vrchat-user-agent", response_class=HTMLResponse)
async def update_vrchat_user_agent(
    request: Request, user_agent: str = Form(...), db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    await app_config_service.set_vrchat_user_agent(db, user_agent)
    return templates.TemplateResponse(
        request,
        "settings/_vrchat_user_agent_form.html",
        {"vrchat_user_agent": user_agent, "saved": True},
    )
