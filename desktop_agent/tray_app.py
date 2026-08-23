"""タスクトレイ常駐UI（pystray + Pillow。ビルド専用の依存関係、requirements-build.txt参照）。"""

from __future__ import annotations

import logging
import tempfile
import threading
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from desktop_agent import startup, updater
from desktop_agent.config import AgentConfig
from desktop_agent.version import __version__

logger = logging.getLogger("gamelog_watcher.tray")

_UPDATE_CHECK_INTERVAL_SECONDS = 6 * 60 * 60


def _build_icon_image() -> Image.Image:
    """外部アセットを使わず、シンプルな円+"V"のアイコンをその場で生成する。"""
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, size - 2, size - 2), fill=(139, 92, 246, 255))
    draw.line((20, 22, 32, 44), fill=(255, 255, 255, 255), width=6)
    draw.line((44, 22, 32, 44), fill=(255, 255, 255, 255), width=6)
    return image


def check_and_apply_update(config: AgentConfig, exe_path: Path) -> bool:
    """新しいバージョンがあれば適用して再起動する。適用した場合はTrueを返す（この関数は戻らない）。"""
    info = updater.fetch_latest_version(config.server_url, config.api_key)
    if not info:
        return False
    remote_version = str(info.get("version") or "")
    if not remote_version or not updater.is_newer(remote_version, __version__):
        return False

    logger.info("新しいバージョン%sが見つかりました。ダウンロードします。", remote_version)
    tmp_path = Path(tempfile.gettempdir()) / "vrc_dashboard_agent_update.exe"
    if not updater.download_update(config.server_url, config.api_key, tmp_path):
        return False

    updater.apply_update_and_restart(tmp_path, exe_path)
    return True  # pragma: no cover — apply_update_and_restartがプロセスを終了させるため到達しない


def _update_check_loop(config: AgentConfig, exe_path: Path, stop_event: threading.Event) -> None:
    while not stop_event.wait(_UPDATE_CHECK_INTERVAL_SECONDS):
        try:
            check_and_apply_update(config, exe_path)
        except Exception:
            logger.exception("自動更新チェックで予期しないエラーが発生しました")


def run_tray(*, config: AgentConfig, exe_path: Path | None) -> None:
    """トレイアイコンを表示し、呼び出し元スレッドをブロックする（Windowsのメッセージループ用にメインスレッドで呼ぶこと）。

    exe_pathがNone（PyInstallerでexe化されていない開発実行時）の場合、自己更新の対象が
    無いため自動更新チェック・「今すぐ更新を確認」・「スタートアップに登録」は無効になる。
    """
    stop_event = threading.Event()
    if exe_path is not None:
        update_thread = threading.Thread(
            target=_update_check_loop, args=(config, exe_path, stop_event), daemon=True
        )
        update_thread.start()

    def on_open_dashboard(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        webbrowser.open(config.server_url)

    def on_check_update(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if exe_path is None:
            icon.notify("開発実行では自動更新は利用できません。", "VRCダッシュボード連携ツール")
            return
        try:
            updated = check_and_apply_update(config, exe_path)
        except Exception:
            logger.exception("手動更新チェックで予期しないエラーが発生しました")
            return
        if not updated:
            icon.notify("最新バージョンです。", "VRCダッシュボード連携ツール")

    def is_startup_registered(item: pystray.MenuItem) -> bool:
        return exe_path is not None and startup.is_registered()

    def on_toggle_startup(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if exe_path is None:
            icon.notify(
                "開発実行ではスタートアップ登録は利用できません。", "VRCダッシュボード連携ツール"
            )
            return
        if startup.is_registered():
            startup.unregister()
        else:
            startup.register(str(exe_path))

    def on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        stop_event.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(f"VRCダッシュボード連携ツール v{__version__}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("ダッシュボードを開く", on_open_dashboard),
        pystray.MenuItem("今すぐ更新を確認", on_check_update),
        pystray.MenuItem("スタートアップに登録", on_toggle_startup, checked=is_startup_registered),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", on_quit),
    )

    icon = pystray.Icon(
        "vrc_dashboard_agent", _build_icon_image(), "VRCダッシュボード連携ツール", menu
    )
    icon.run()
