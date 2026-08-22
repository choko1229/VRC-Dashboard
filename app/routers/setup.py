"""初回セットアップ（Discord OAuthアプリ情報の登録）。

ログイン機構自体がDiscord OAuthに依存するため、初回だけは未認証でアクセスできる
専用の画面を用意する（一般的なセルフホストアプリの初回セットアップ画面と同様のパターン）。
一度設定が完了した後は、このルートからの変更はできなくなる
（変更する場合は認証後の/settings/generalから行う）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_cipher
from app.core.security import SecretCipher
from app.core.templating import templates
from app.db.session import get_db
from app.services import app_config_service

router = APIRouter()


@router.get("/setup", response_class=HTMLResponse, response_model=None)
async def setup_page(
    request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse | RedirectResponse:
    if await app_config_service.is_discord_oauth_configured(db):
        return RedirectResponse(url="/login", status_code=302)

    redirect_uri = str(request.url_for("discord_callback"))
    return templates.TemplateResponse(
        request, "setup/index.html", {"redirect_uri": redirect_uri}
    )


@router.post("/setup/discord", response_class=HTMLResponse, response_model=None)
async def setup_discord(
    request: Request,
    client_id: str = Form(...),
    client_secret: str = Form(...),
    db: AsyncSession = Depends(get_db),
    cipher: SecretCipher = Depends(get_cipher),
) -> HTMLResponse | RedirectResponse:
    if await app_config_service.is_discord_oauth_configured(db):
        return RedirectResponse(url="/login", status_code=302)

    await app_config_service.set_discord_oauth_config(
        db, cipher, client_id=client_id, client_secret=client_secret
    )
    return RedirectResponse(url="/login", status_code=302)
