"""Windowsのスタートアップ（ログイン時自動起動）への登録・解除。

レジストリの`HKCU\\...\\Run`を使う（ショートカット(.lnk)作成にはpywin32が要るため、
標準ライブラリの`winreg`だけで完結するこちらを採用している）。
"""

from __future__ import annotations

import winreg

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "VRCDashboardAgent"


def is_registered() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def register(exe_path: str) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')


def unregister() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        pass
