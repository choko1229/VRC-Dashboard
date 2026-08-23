"""デスクトップエージェント（desktop_agent/）の配布用ビルド(exe)の管理。

サーバーはビルド済みexeを1つだけ保持する単純な「最新版」置き換え方式（バージョン履歴は
持たない）。ビルド自体は`desktop_agent/build.ps1`で作成し、管理者が`/game-log`から
アップロードする。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import app_config_service

_RELEASES_DIR = Path("data/agent_releases")
_EXE_FILENAME = "VRCDashboardAgent.exe"


def release_exe_path() -> Path:
    return _RELEASES_DIR / _EXE_FILENAME


def has_release() -> bool:
    return release_exe_path().exists()


async def get_latest_version(db: AsyncSession) -> str | None:
    return await app_config_service.get_game_log_agent_version(db)


async def save_release(db: AsyncSession, *, version: str, content: bytes) -> None:
    _RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    release_exe_path().write_bytes(content)
    await app_config_service.set_game_log_agent_version(db, version)
