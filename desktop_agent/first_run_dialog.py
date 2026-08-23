"""初回起動時にダッシュボードURLを入力してもらい、ブラウザでのペアリングログインへ導く
簡易ダイアログ（tkinter、標準ライブラリのみ）。

以前はAPIキーの手動コピー&ペーストを求めていたが、ブラウザでログイン→コードを承認、
という流れ（desktop_agent.device_pairing）に置き換えた。
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox

from desktop_agent.config import AgentConfig
from desktop_agent.device_pairing import pair_with_browser

logger = logging.getLogger("gamelog_watcher.first_run_dialog")


def prompt_for_config() -> AgentConfig | None:
    """URL入力→ペアリング承認待ちを行う。成功時はAgentConfigを、キャンセル時はNoneを返す。"""
    root = tk.Tk()
    root.title("VRCダッシュボード連携ツール - 初期設定")
    root.resizable(False, False)

    result: dict[str, AgentConfig | None] = {"value": None}

    frame = tk.Frame(root)
    frame.pack(padx=16, pady=16)

    tk.Label(frame, text="ダッシュボードのURL（例: https://vrc.example.com）").pack(anchor="w")
    server_entry = tk.Entry(frame, width=48)
    server_entry.pack(pady=(4, 8))
    server_entry.focus_set()

    status_label = tk.Label(frame, text="", fg="#666666", wraplength=360, justify="left")
    status_label.pack(anchor="w", pady=(0, 8))

    start_button = tk.Button(frame, text="ブラウザでログインして開始")
    start_button.pack()

    def on_pairing_result(token: str | None, server_url: str) -> None:
        if token is None:
            status_label.config(text="承認されませんでした。もう一度お試しください。")
            start_button.config(state=tk.NORMAL)
            return
        result["value"] = AgentConfig(server_url=server_url, api_key=token)
        root.destroy()

    def run_pairing_in_background(server_url: str) -> None:
        token: str | None = None
        try:
            token = pair_with_browser(server_url)
        except Exception:
            logger.exception("ペアリングに失敗しました")
        # tkinterはメインスレッド以外からのUI操作が不可なため、after()で戻す。
        root.after(0, on_pairing_result, token, server_url)

    def on_start() -> None:
        server_url = server_entry.get().strip()
        if not server_url:
            messagebox.showerror("入力エラー", "URLを入力してください。", parent=root)
            return
        start_button.config(state=tk.DISABLED)
        status_label.config(
            text="ブラウザが開きます。ダッシュボードにログインし、"
            "表示されたコードを承認してください..."
        )
        threading.Thread(
            target=run_pairing_in_background, args=(server_url,), daemon=True
        ).start()

    start_button.config(command=on_start)

    root.mainloop()
    return result["value"]
