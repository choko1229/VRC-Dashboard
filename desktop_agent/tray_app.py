"""タスクトレイ常駐UI（pystray + Pillow。ビルド専用の依存関係、requirements-build.txt参照）。"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import webbrowser
from pathlib import Path

import pystray

from desktop_agent import branding, startup, updater
from desktop_agent.config import AgentConfig, save_config
from desktop_agent.device_pairing import PairingError, pair_with_browser
from desktop_agent.version import __version__

logger = logging.getLogger("gamelog_watcher.tray")

_UPDATE_CHECK_INTERVAL_SECONDS = 6 * 60 * 60


def check_and_apply_update(exe_path: Path) -> bool:
    """GitHub Releasesに新しいバージョンがあれば適用して再起動する。

    適用した場合はTrueを返す（実際にはapply_update_and_restartがプロセスを終了させるため
    この関数からは戻らない）。
    """
    release = updater.fetch_latest_release()
    if not release:
        return False
    extracted = updater.extract_version_and_asset_url(release)
    if extracted is None:
        return False
    remote_version, download_url = extracted
    if not updater.is_newer(remote_version, __version__):
        return False

    logger.info("新しいバージョン%sが見つかりました。ダウンロードします。", remote_version)
    tmp_path = Path(tempfile.gettempdir()) / "vrc_dashboard_agent_update.exe"
    if not updater.download_asset(download_url, tmp_path):
        return False

    updater.apply_update_and_restart(tmp_path, exe_path)
    return True  # pragma: no cover — apply_update_and_restartがプロセスを終了させるため到達しない


def _update_check_loop(exe_path: Path, stop_event: threading.Event) -> None:
    while not stop_event.wait(_UPDATE_CHECK_INTERVAL_SECONDS):
        try:
            check_and_apply_update(exe_path)
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
            target=_update_check_loop, args=(exe_path, stop_event), daemon=True
        )
        update_thread.start()

    def on_open_dashboard(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        webbrowser.open(config.server_url)

    def on_check_update(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if exe_path is None:
            icon.notify("開発実行では自動更新は利用できません。", branding.APP_NAME)
            return
        try:
            updated = check_and_apply_update(exe_path)
        except Exception:
            logger.exception("手動更新チェックで予期しないエラーが発生しました")
            return
        if not updated:
            icon.notify("最新バージョンです。", branding.APP_NAME)

    def on_relogin(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        icon.notify(
            "ブラウザが開きます。ログインしてコードを承認してください。",
            branding.APP_NAME,
        )
        try:
            token = pair_with_browser(config.server_url)
        except PairingError as exc:
            logger.warning("再ログインに失敗しました: %s", exc)
            icon.notify(str(exc), branding.APP_NAME)
            return
        except Exception:
            logger.exception("再ログインで予期しないエラーが発生しました")
            icon.notify("予期しないエラーが発生しました。", branding.APP_NAME)
            return
        if token is None:
            icon.notify(
                "承認されませんでした（タイムアウトまたは拒否）。", branding.APP_NAME
            )
            return

        save_config(AgentConfig(server_url=config.server_url, api_key=token))
        if exe_path is None:
            icon.notify(
                "ログインしました。開発実行のため手動で再起動してください。",
                branding.APP_NAME,
            )
            return
        icon.notify("ログインしました。再起動します。", branding.APP_NAME)
        subprocess.Popen([str(exe_path)], close_fds=True)
        os._exit(0)

    def is_startup_registered(item: pystray.MenuItem) -> bool:
        return exe_path is not None and startup.is_registered()

    def on_toggle_startup(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if exe_path is None:
            icon.notify(
                "開発実行ではスタートアップ登録は利用できません。", branding.APP_NAME
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
        pystray.MenuItem(f"{branding.APP_NAME} v{__version__}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("ダッシュボードを開く", on_open_dashboard),
        pystray.MenuItem("ログインし直す", on_relogin),
        pystray.MenuItem("今すぐ更新を確認", on_check_update),
        pystray.MenuItem("スタートアップに登録", on_toggle_startup, checked=is_startup_registered),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", on_quit),
    )

    icon = pystray.Icon(
        "vrc_dashboard_agent", branding.build_icon_image(), branding.APP_NAME, menu
    )
    icon.run()
