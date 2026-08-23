"""VRCダッシュボード連携ツールのエントリポイント（タスクトレイ常駐・自動更新・ゲームログ収集）。

開発時: `python -m desktop_agent.main`
配布時: `build.ps1`でPyInstallerによりこのファイルを起点にexe化する。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import truststore

# WindowsのOS証明書ストアを使ってTLS検証する（PyInstallerが同梱するOpenSSLの証明書検証が、
# 環境によってはGitHubのTLS証明書チェーンを検証できない場合があるため。curl等が使う
# ネイティブ検証と同じ結果になるよう、標準のssl検証をこれに差し替える）。
# HTTPS通信を行うどのコードよりも先に実行する必要がある。
truststore.inject_into_ssl()

# PyInstallerでexe化した状態・`python desktop_agent/main.py`で直接実行した状態の両方で
# `desktop_agent`パッケージを絶対importできるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desktop_agent.config import load_config, save_config  # noqa: E402
from desktop_agent.first_run_dialog import prompt_for_config  # noqa: E402
from desktop_agent.gamelog_watcher import GameLogWatcher, default_log_dir  # noqa: E402
from desktop_agent.paths import installed_exe_path, state_file  # noqa: E402
from desktop_agent.tray_app import run_tray  # noqa: E402
from desktop_agent.updater import cleanup_old_files  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gamelog_watcher.main")


def _ensure_installed_copy() -> Path | None:
    """初回起動時、実行ファイルを書き込み可能な安定パス（%LOCALAPPDATA%）にコピーして再起動する。

    自己更新は実行中のファイルを置き換える都合上、書き込み可能な安定した場所に配置されて
    いる必要がある。ソースから直接実行する開発時（PyInstallerでexe化されていない場合）は
    自己更新の対象パスが無いためNoneを返す（自動更新機能は無効になる）。
    """
    if not getattr(sys, "frozen", False):
        return None

    current_path = Path(sys.executable).resolve()
    target_path = installed_exe_path()
    if current_path == target_path:
        return current_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current_path, target_path)
    subprocess.Popen([str(target_path)], close_fds=True)
    sys.exit(0)


def main() -> None:
    exe_path = _ensure_installed_copy()
    if exe_path is not None:
        cleanup_old_files(exe_path.parent)

    config = load_config()
    if config is None:
        config = prompt_for_config()
        if config is None:
            logger.info("初期設定がキャンセルされたため終了します。")
            return
        save_config(config)

    watcher = GameLogWatcher(
        server_url=config.server_url,
        api_key=config.api_key,
        log_dir=default_log_dir(),
        state_file=state_file(),
    )
    watcher_thread = threading.Thread(target=watcher.run_forever, daemon=True)
    watcher_thread.start()

    run_tray(config=config, exe_path=exe_path)


if __name__ == "__main__":
    main()
