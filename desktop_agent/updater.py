"""自動更新: GitHub Releasesでのバージョン確認・ダウンロード・自己置換（標準ライブラリのみ）。"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path

logger = logging.getLogger("gamelog_watcher.updater")

# 配布はGitHub Releasesで行う（desktop_agent/build.ps1でこのリポジトリへリリースを作成する）。
GITHUB_REPO = "choko1229/VRC-Dashboard"
RELEASE_TAG_PREFIX = "desktop-agent-v"


def parse_version(version: str) -> tuple[int, ...]:
    """"1.2.3" のようなバージョン文字列を比較可能なタプルにする。数字以外は無視する。"""
    parts: list[int] = []
    for chunk in version.strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(remote_version: str, local_version: str) -> bool:
    return parse_version(remote_version) > parse_version(local_version)


def fetch_latest_release(repo: str = GITHUB_REPO) -> dict[str, object] | None:
    """GitHub Releasesの最新リリース情報を取得する（公開リポジトリのため認証不要）。"""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "VRCDashboardAgent"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload: dict[str, object] = json.loads(response.read().decode("utf-8"))
            return payload
    except (urllib.error.URLError, ValueError) as exc:
        logger.warning("GitHub Releasesの確認に失敗しました: %s", exc)
        return None


def extract_version_and_asset_url(release: Mapping[str, object]) -> tuple[str, str] | None:
    """リリース情報から(バージョン, exeアセットのダウンロードURL)を取り出す。該当が無ければNone。"""
    tag_name = str(release.get("tag_name") or "")
    if not tag_name.startswith(RELEASE_TAG_PREFIX):
        return None
    version = tag_name.removeprefix(RELEASE_TAG_PREFIX)

    assets = release.get("assets")
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        download_url = asset.get("browser_download_url")
        if isinstance(name, str) and name.endswith(".exe") and isinstance(download_url, str):
            return version, download_url
    return None


def download_asset(download_url: str, dest_path: Path) -> bool:
    request = urllib.request.Request(download_url, headers={"User-Agent": "VRCDashboardAgent"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with dest_path.open("wb") as fp:
                shutil.copyfileobj(response, fp)
        return dest_path.stat().st_size > 0
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("更新ファイルのダウンロードに失敗しました: %s", exc)
        return False


def cleanup_old_files(directory: Path) -> None:
    """前回の自己更新で残った`*.old`ファイルを削除する（起動時に呼ぶ）。"""
    for old_file in directory.glob("*.old"):
        try:
            old_file.unlink()
        except OSError:
            logger.debug("古いファイルの削除に失敗しました: %s", old_file)


def apply_update_and_restart(new_exe_path: Path, current_exe_path: Path) -> None:
    """新しいexeを現在の実行ファイルの場所に入れ替え、新プロセスを起動して自分は終了する。

    Windowsでは実行中のexeファイルもリネームできる（既存のプロセスは開いたハンドルを
    保持したまま動き続ける）ため、現在のexeを`.old`にリネームしてから新しいexeを配置する。
    `.old`ファイル自体の削除は次回起動時の`cleanup_old_files`に委ねる
    （このプロセスがまだハンドルを持っているため今すぐは削除できない）。
    """
    old_path = current_exe_path.with_suffix(current_exe_path.suffix + ".old")
    old_path.unlink(missing_ok=True)
    if current_exe_path.exists():
        current_exe_path.rename(old_path)
    shutil.move(str(new_exe_path), str(current_exe_path))
    subprocess.Popen([str(current_exe_path)], close_fds=True)
    os._exit(0)
