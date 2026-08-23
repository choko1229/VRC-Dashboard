"""インスタンスごとのゲームログ（ローカルエージェント連携）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin_user, get_current_user, require_game_log_api_key
from app.core.templating import templates
from app.db.session import get_db
from app.schemas.game_log import AgentVersionResponse, GameLogIngestRequest
from app.services import agent_release_service, app_config_service, game_log_service

router = APIRouter()

_AGENT_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "desktop_agent" / "gamelog_watcher.py"
)


async def _setup_panel_context(
    db: AsyncSession, *, new_api_key: str | None = None
) -> dict[str, object]:
    return {
        "is_configured": await app_config_service.is_game_log_api_key_configured(db),
        "new_api_key": new_api_key,
        "agent_version": await agent_release_service.get_latest_version(db),
        "agent_download_available": agent_release_service.has_release(),
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
    return FileResponse(
        _AGENT_SCRIPT_PATH, media_type="text/x-python", filename="gamelog_watcher.py"
    )


@router.get(
    "/game-log/agent/download",
    dependencies=[Depends(get_current_user)],
    include_in_schema=False,
)
async def download_agent_exe_for_browser() -> FileResponse:
    """管理画面からの手動ダウンロード用（セッションCookie認証）。"""
    if not agent_release_service.has_release():
        raise HTTPException(status_code=404, detail="配布中のビルドがありません。")
    return FileResponse(
        agent_release_service.release_exe_path(),
        media_type="application/octet-stream",
        filename="VRCDashboardAgent.exe",
    )


@router.get(
    "/api/game-log/agent/version",
    dependencies=[Depends(require_game_log_api_key)],
    response_model=AgentVersionResponse,
)
async def agent_version(db: AsyncSession = Depends(get_db)) -> AgentVersionResponse:
    """デスクトップエージェント自身の自己更新チェック用（APIキー認証）。"""
    version = await agent_release_service.get_latest_version(db)
    return AgentVersionResponse(
        version=version or "0.0.0",
        download_available=agent_release_service.has_release(),
    )


@router.get(
    "/api/game-log/agent/download",
    dependencies=[Depends(require_game_log_api_key)],
)
async def download_agent_exe_for_agent() -> FileResponse:
    """デスクトップエージェント自身の自己更新ダウンロード用（APIキー認証）。"""
    if not agent_release_service.has_release():
        raise HTTPException(status_code=404, detail="配布中のビルドがありません。")
    return FileResponse(
        agent_release_service.release_exe_path(),
        media_type="application/octet-stream",
        filename="VRCDashboardAgent.exe",
    )


@router.post(
    "/game-log/agent/release",
    response_class=HTMLResponse,
    dependencies=[Depends(get_current_admin_user)],
)
async def upload_agent_release(
    request: Request,
    version: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    content = await file.read()
    await agent_release_service.save_release(db, version=version.strip(), content=content)
    return templates.TemplateResponse(
        request, "game_log/_setup_panel.html", await _setup_panel_context(db)
    )


@router.post(
    "/game-log/api-key",
    response_class=HTMLResponse,
    dependencies=[Depends(get_current_admin_user)],
)
async def generate_game_log_api_key(
    request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    raw_key = await app_config_service.generate_game_log_api_key(db)
    return templates.TemplateResponse(
        request,
        "game_log/_setup_panel.html",
        await _setup_panel_context(db, new_api_key=raw_key),
    )


@router.delete(
    "/game-log/api-key",
    response_class=HTMLResponse,
    dependencies=[Depends(get_current_admin_user)],
)
async def revoke_game_log_api_key(
    request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    await app_config_service.revoke_game_log_api_key(db)
    return templates.TemplateResponse(
        request, "game_log/_setup_panel.html", await _setup_panel_context(db)
    )


@router.post(
    "/api/game-log/events",
    dependencies=[Depends(require_game_log_api_key)],
)
async def ingest_game_log_events(
    payload: GameLogIngestRequest, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    await game_log_service.ingest_events(db, payload.events)
    return JSONResponse({"accepted": len(payload.events)})
