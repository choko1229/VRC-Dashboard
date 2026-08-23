"""自動更新: バージョン確認・ダウンロード・自己置換。標準ライブラリのみに依存する。"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("gamelog_watcher.updater")


def parse_version(version: str) -> tuple[int, ...]:
    """"1.2.3" のようなバージョン文字列を比較可能なタプルにする。数字以外は無視する。"""
    parts: list[int] = []
    for chunk in version.strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(remote_version: str, local_version: str) -> bool:
    return parse_version(remote_version) > parse_version(local_version)


def fetch_latest_version(server_url: str, api_key: str) -> dict[str, object] | None:
    url = server_url.rstrip("/") + "/api/game-log/agent/version"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload: dict[str, object] = json.loads(response.read().decode("utf-8"))
            return payload
    except (urllib.error.URLError, ValueError) as exc:
        logger.warning("バージョン確認に失敗しました: %s", exc)
        return None


def download_update(server_url: str, api_key: str, dest_path: Path) -> bool:
    url = server_url.rstrip("/") + "/api/game-log/agent/download"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
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
