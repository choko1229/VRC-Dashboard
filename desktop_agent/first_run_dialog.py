"""初回起動時にダッシュボードURL・APIキーを入力してもらう簡易ダイアログ（tkinter、標準ライブラリのみ）。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from desktop_agent.config import AgentConfig


def prompt_for_config() -> AgentConfig | None:
    """入力を受け付け、保存前の設定を返す。ウィンドウを閉じた場合はNoneを返す。"""
    root = tk.Tk()
    root.title("VRCダッシュボード連携ツール - 初期設定")
    root.resizable(False, False)

    tk.Label(root, text="ダッシュボードのURL（例: https://vrc.example.com）").grid(
        row=0, column=0, sticky="w", padx=10, pady=(10, 0)
    )
    server_entry = tk.Entry(root, width=48)
    server_entry.grid(row=1, column=0, padx=10)

    tk.Label(root, text="APIキー（ダッシュボードの/game-logで発行）").grid(
        row=2, column=0, sticky="w", padx=10, pady=(10, 0)
    )
    key_entry = tk.Entry(root, width=48, show="*")
    key_entry.grid(row=3, column=0, padx=10)

    result: dict[str, AgentConfig | None] = {"value": None}

    def on_submit() -> None:
        server_url = server_entry.get().strip()
        api_key = key_entry.get().strip()
        if not server_url or not api_key:
            messagebox.showerror("入力エラー", "両方入力してください。", parent=root)
            return
        result["value"] = AgentConfig(server_url=server_url, api_key=api_key)
        root.destroy()

    tk.Button(root, text="保存して開始", command=on_submit).grid(
        row=4, column=0, pady=10
    )
    server_entry.focus_set()
    root.mainloop()
    return result["value"]
