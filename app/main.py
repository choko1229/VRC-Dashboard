"""FastAPIアプリのエントリポイント。"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import InvalidGameLogApiKeyError, NotAdminError, NotAuthenticatedError
from app.core.logging import configure_logging
from app.core.security import get_secret_cipher
from app.core.templating import templates
from app.db.base import create_engine_and_sessionmaker
from app.notifications.base import NotificationSender
from app.notifications.composite import CompositeNotificationSender
from app.notifications.webpush_sender import WebPushSender
from app.routers import (
    auth,
    avatars,
    dashboard,
    feed,
    friends,
    game_log,
    play_stats,
    schedule,
    settings,
    setup,
    vrchat_notifications,
    webpush,
)
from app.services import app_config_service, notification_service, vrchat_session_service
from app.services.vrchat.pipeline import PipelineManager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings_obj = get_settings()
    engine, session_factory = create_engine_and_sessionmaker(
        settings_obj.database_url, echo=settings_obj.debug
    )
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    cipher = get_secret_cipher(settings_obj)

    # VAPID鍵は.envではなくDB管理。未生成であれば起動時に自動生成する。
    async with session_factory() as db:
        vapid_private_key, vapid_public_key = await app_config_service.get_or_create_vapid_keys(
            db, cipher
        )
        vapid_contact_email = await app_config_service.get_vapid_contact_email(db)

    webpush_sender = WebPushSender(
        session_factory=session_factory,
        vapid_private_key=vapid_private_key,
        vapid_public_key=vapid_public_key,
        vapid_contact_email=vapid_contact_email,
    )

    async def notification_sender_factory(db: AsyncSession) -> NotificationSender:
        discord_sender = await notification_service.build_discord_sender(db, cipher)
        return CompositeNotificationSender([discord_sender, webpush_sender])

    async def get_auth_cookie() -> str | None:
        async with session_factory() as db:
            cookies = await vrchat_session_service.get_decrypted_cookies(db, cipher)
            return cookies[0] if cookies else None

    async def get_user_agent() -> str:
        async with session_factory() as db:
            return await app_config_service.get_vrchat_user_agent(db)

    pipeline_manager = PipelineManager(
        session_factory=session_factory,
        notification_sender_factory=notification_sender_factory,
        get_auth_cookie=get_auth_cookie,
        get_user_agent=get_user_agent,
        initial_reconnect_seconds=settings_obj.pipeline_reconnect_initial_seconds,
        max_reconnect_seconds=settings_obj.pipeline_reconnect_max_seconds,
        notify_after_failures=settings_obj.pipeline_reconnect_notify_after_failures,
    )
    app.state.pipeline_manager = pipeline_manager

    async with session_factory() as db:
        existing_session = await vrchat_session_service.get_active_session(db)
    if existing_session is not None:
        pipeline_manager.start()

    logger.info("アプリを起動しました (env=%s)", settings_obj.app_env)
    yield

    await pipeline_manager.stop()
    await engine.dispose()
    logger.info("アプリを停止しました")


def create_app() -> FastAPI:
    settings_obj = get_settings()
    configure_logging(debug=settings_obj.debug)

    app = FastAPI(title="VRC事前確認ダッシュボード", lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def no_heuristic_cache_for_static(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # StaticFilesはCache-Controlを付与しないため、ブラウザの発見的キャッシュにより
        # 更新したCSS/JSが反映されないことがある。ETagでの再検証を毎回強制する。
        response = await call_next(request)
        if request.url.path.startswith("/static/") or request.url.path == "/sw.js":
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.include_router(setup.router)
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(settings.router)
    app.include_router(friends.router)
    app.include_router(avatars.router)
    app.include_router(schedule.router)
    app.include_router(webpush.router)
    app.include_router(game_log.router)
    app.include_router(feed.router)
    app.include_router(vrchat_notifications.router)
    app.include_router(play_stats.router)

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker() -> FileResponse:
        # Push購読のscopeをオリジン全体("/")にするため、/static配下ではなくルートで配信する。
        return FileResponse(STATIC_DIR / "js" / "sw.js", media_type="application/javascript")

    @app.exception_handler(NotAuthenticatedError)
    async def handle_not_authenticated(
        request: Request, exc: NotAuthenticatedError
    ) -> RedirectResponse:
        return RedirectResponse(url="/login", status_code=302)

    @app.exception_handler(NotAdminError)
    async def handle_not_admin(request: Request, exc: NotAdminError) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "errors/forbidden.html",
            {"reason": "この操作には管理者権限が必要です。"},
            status_code=403,
        )

    @app.exception_handler(InvalidGameLogApiKeyError)
    async def handle_invalid_game_log_api_key(
        request: Request, exc: InvalidGameLogApiKeyError
    ) -> JSONResponse:
        return JSONResponse({"detail": "APIキーが無効です。"}, status_code=401)

    return app


app = create_app()
