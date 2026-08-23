"""エージェントが使うファイルパス（設定・状態・自己更新後の設置先）の解決。

自己更新（実行中のexeを新しいものに入れ替える）には書き込み可能な安定したパスが要るため、
初回起動時に`%LOCALAPPDATA%\\VRCDashboardAgent\\`へ自分自身をコピーして常駐する。
"""

from __future__ import annotations

import os
from pathlib import Path

_APP_DIR_NAME = "VRCDashboardAgent"
INSTALLED_EXE_NAME = "VRCDashboardAgent.exe"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    directory = Path(base) / _APP_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_file() -> Path:
    return app_data_dir() / "config.json"


def state_file() -> Path:
    return app_data_dir() / "gamelog_agent_state.json"


def installed_exe_path() -> Path:
    return app_data_dir() / INSTALLED_EXE_NAME
