"""インスタンスごとのゲームログ（デスクトップエージェント連携）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin_user, get_current_user, require_game_log_api_key
from app.core.templating import templates
from app.db.session import get_db
from app.schemas.game_log import (
    DeviceCodeResponse,
    DevicePollRequest,
    DevicePollResponse,
    GameLogIngestRequest,
)
from app.services import device_auth_service, game_log_agent_token_service, game_log_service

router = APIRouter()

_AGENT_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "desktop_agent" / "gamelog_watcher.py"
)
# 配布はGitHub Releasesで行う（desktop_agent/build.ps1参照）。サーバーはバイナリを保持しない。
_GITHUB_RELEASES_URL = "https://github.com/choko1229/VRC-Dashboard/releases"


async def _setup_panel_context(db: AsyncSession) -> dict[str, object]:
    return {
        "agent_tokens": await game_log_agent_token_service.list_tokens(db),
        "github_releases_url": _GITHUB_RELEASES_URL,
    }


@router.get("/game-log", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
async def game_log_page(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    summaries, has_more = await game_log_service.get_instance_summaries(db, page=0)
    return templates.TemplateResponse(
        request,
        "game_log/list.html",
        {
            "summaries": summaries,
            "has_more": has_more,
            "next_page": 1,
            "is_first_page": True,
            **(await _setup_panel_context(db)),
        },
    )


@router.get(
    "/game-log/page/{page}", response_class=HTMLResponse, dependencies=[Depends(get_current_user)]
)
async def game_log_page_partial(
    request: Request, page: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    summaries, has_more = await game_log_service.get_instance_summaries(db, page=page)
    return templates.TemplateResponse(
        request,
        "game_log/_instance_batch.html",
        {
            "summaries": summaries,
            "has_more": has_more,
            "next_page": page + 1,
            "is_first_page": False,
        },
    )


@router.get(
    "/game-log/{instance_id}/events",
    response_class=HTMLResponse,
    dependencies=[Depends(get_current_user)],
)
async def game_log_instance_events(
    request: Request, instance_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    events = await game_log_service.get_instance_events(db, instance_id)
    return templates.TemplateResponse(
        request, "game_log/_instance_events.html", {"events": events}
    )


@router.get(
    "/game-log/agent-script", dependencies=[Depends(get_current_user)], include_in_schema=False
)
async def download_agent_script() -> FileResponse:
    """Pythonをそのまま動かしたい場合のフォールバック配布（通常はGitHub Releasesのexeを使う）。"""
    return FileResponse(
        _AGENT_SCRIPT_PATH, media_type="text/x-python", filename="gamelog_watcher.py"
    )


@router.delete(
    "/game-log/agent-token/{token_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(get_current_admin_user)],
)
async def revoke_agent_token(
    request: Request, token_id: int, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    await game_log_agent_token_service.revoke_token(db, token_id)
    return templates.TemplateResponse(
        request, "game_log/_setup_panel.html", await _setup_panel_context(db)
    )


@router.get(
    "/game-log/device",
    response_class=HTMLResponse,
    dependencies=[Depends(get_current_user)],
)
async def device_verification_page(request: Request, code: str = "") -> HTMLResponse:
    """デスクトップエージェントが開くペアリング承認画面。管理者としてログインしている必要がある。"""
    return templates.TemplateResponse(
        request, "game_log/device.html", {"prefilled_code": code, "result": None}
    )


@router.post(
    "/game-log/device/approve",
    response_class=HTMLResponse,
    dependencies=[Depends(get_current_admin_user)],
)
async def approve_device(
    request: Request,
    user_code: str = Form(...),
    label: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    approved = await device_auth_service.approve(db, user_code, label=label.strip() or None)
    return templates.TemplateResponse(
        request,
        "game_log/_device_result.html",
        {"result": "approved" if approved else "not_found"},
    )


@router.post(
    "/game-log/device/deny",
    response_class=HTMLResponse,
    dependencies=[Depends(get_current_admin_user)],
)
async def deny_device(request: Request, user_code: str = Form(...)) -> HTMLResponse:
    denied = device_auth_service.deny(user_code)
    return templates.TemplateResponse(
        request,
        "game_log/_device_result.html",
        {"result": "denied" if denied else "not_found"},
    )


@router.post(
    "/api/game-log/agent/pair",
    response_model=DeviceCodeResponse,
    include_in_schema=False,
)
async def create_device_pairing(request: Request) -> DeviceCodeResponse:
    """デスクトップエージェント起動時に呼ばれる。認証不要（このコード自体が短命の共有シークレット）。"""
    entry = device_auth_service.create_device_code()
    verification_uri = str(
        request.url_for("device_verification_page").include_query_params(code=entry.user_code)
    )
    return DeviceCodeResponse(
        device_code=entry.device_code,
        user_code=entry.user_code,
        verification_uri=verification_uri,
        expires_in=device_auth_service.CODE_TTL_SECONDS,
        interval=device_auth_service.POLL_INTERVAL_SECONDS,
    )


@router.post(
    "/api/game-log/agent/pair/poll",
    response_model=DevicePollResponse,
    include_in_schema=False,
)
async def poll_device_pairing(payload: DevicePollRequest) -> DevicePollResponse:
    entry = device_auth_service.poll(payload.device_code)
    if entry is None:
        return DevicePollResponse(status="expired_or_unknown")
    if entry.status == "approved":
        return DevicePollResponse(status="approved", token=entry.issued_token)
    if entry.status == "denied":
        return DevicePollResponse(status="denied")
    return DevicePollResponse(status="pending")


@router.post(
    "/api/game-log/events",
    dependencies=[Depends(require_game_log_api_key)],
)
async def ingest_game_log_events(
    payload: GameLogIngestRequest, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    await game_log_service.ingest_events(db, payload.events)
    return JSONResponse({"accepted": len(payload.events)})
