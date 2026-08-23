"""初回起動時にダッシュボードURLを入力してもらい、ブラウザでのペアリングログインへ導く
簡易ダイアログ（tkinter、標準ライブラリのみ）。

配色はダッシュボードのWeb UI（app/static/css/tokens.cssの--color-gamelog-*）と
揃えている（desktop_agent/branding.py参照）。tkinter単体ではWeb版と全く同じ見た目には
できないため、フォントは既定のシステムフォント、配色・レイアウトの近似にとどめている。

以前はAPIキーの手動コピー&ペーストを求めていたが、ブラウザでログイン→コードを承認、
という流れ（desktop_agent.device_pairing）に置き換えた。
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox

from PIL import ImageTk

from desktop_agent import branding
from desktop_agent.config import AgentConfig
from desktop_agent.device_pairing import PairingError, pair_with_browser

logger = logging.getLogger("gamelog_watcher.first_run_dialog")

_FONT_FAMILY = "Yu Gothic UI"
_FONT_BODY = (_FONT_FAMILY, 10)
_FONT_HEADING = (_FONT_FAMILY, 13, "bold")
_FONT_BUTTON = (_FONT_FAMILY, 10, "bold")


def prompt_for_config() -> AgentConfig | None:
    """URL入力→ペアリング承認待ちを行う。成功時はAgentConfigを、キャンセル時はNoneを返す。"""
    root = tk.Tk()
    root.title(f"{branding.APP_NAME} - 初期設定")
    root.configure(bg=branding.COLOR_SURFACE)
    root.resizable(False, False)

    # icon_imageはmainloop()が返るまでこの関数のローカル変数として生き続けるため、
    # PhotoImageがガベージコレクトされてアイコンが消える問題は起きない。
    icon_image = ImageTk.PhotoImage(branding.build_icon_image(32))
    root.iconphoto(True, icon_image)  # type: ignore[arg-type]

    result: dict[str, AgentConfig | None] = {"value": None}

    outer = tk.Frame(root, bg=branding.COLOR_SURFACE)
    outer.pack(padx=20, pady=20)

    header = tk.Frame(outer, bg=branding.COLOR_SURFACE)
    header.pack(fill="x", pady=(0, 12))
    tk.Label(
        header,
        text=branding.APP_NAME,
        font=_FONT_HEADING,
        fg=branding.COLOR_PRIMARY,
        bg=branding.COLOR_SURFACE,
    ).pack(anchor="w")
    tk.Label(
        header,
        text="初期設定",
        font=_FONT_BODY,
        fg=branding.COLOR_TEXT_MUTED,
        bg=branding.COLOR_SURFACE,
    ).pack(anchor="w")

    tk.Label(
        outer,
        text="ダッシュボードのURL",
        font=_FONT_BODY,
        fg=branding.COLOR_TEXT,
        bg=branding.COLOR_SURFACE,
    ).pack(anchor="w")
    server_entry = tk.Entry(
        outer,
        width=48,
        font=_FONT_BODY,
        relief="solid",
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=branding.COLOR_BORDER,
        highlightcolor=branding.COLOR_PRIMARY,
    )
    server_entry.insert(0, "https://")
    server_entry.pack(pady=(4, 2), ipady=4)
    server_entry.focus_set()
    server_entry.icursor(tk.END)

    tk.Label(
        outer,
        text="例: vrc.example.com（httpsは省略可）",
        font=(_FONT_FAMILY, 8),
        fg=branding.COLOR_TEXT_MUTED,
        bg=branding.COLOR_SURFACE,
    ).pack(anchor="w", pady=(0, 12))

    status_label = tk.Label(
        outer,
        text="",
        font=_FONT_BODY,
        fg=branding.COLOR_TEXT_MUTED,
        bg=branding.COLOR_SURFACE,
        wraplength=360,
        justify="left",
    )
    status_label.pack(anchor="w", pady=(0, 12))

    start_button = tk.Button(
        outer,
        text="ブラウザでログインして開始",
        font=_FONT_BUTTON,
        fg="#FFFFFF",
        bg=branding.COLOR_PRIMARY,
        activeforeground="#FFFFFF",
        activebackground=branding.COLOR_PRIMARY_HOVER,
        relief="flat",
        borderwidth=0,
        padx=16,
        pady=8,
        cursor="hand2",
    )
    start_button.pack(fill="x")

    def set_status(text: str, *, is_error: bool = False) -> None:
        color = branding.COLOR_DANGER if is_error else branding.COLOR_TEXT_MUTED
        status_label.config(text=text, fg=color)

    def on_pairing_success(token: str, server_url: str) -> None:
        result["value"] = AgentConfig(server_url=server_url, api_key=token)
        root.destroy()

    def on_pairing_failed(message: str) -> None:
        set_status(message, is_error=True)
        start_button.config(state=tk.NORMAL)

    def run_pairing_in_background(server_url: str) -> None:
        try:
            token = pair_with_browser(server_url)
        except PairingError as exc:
            logger.warning("ペアリングに失敗しました: %s", exc)
            # tkinterはメインスレッド以外からのUI操作が不可なため、after()で戻す。
            root.after(0, on_pairing_failed, str(exc))
            return
        except Exception:
            logger.exception("ペアリングで予期しないエラーが発生しました")
            root.after(0, on_pairing_failed, "予期しないエラーが発生しました。")
            return

        if token is None:
            root.after(
                0, on_pairing_failed, "承認されませんでした。もう一度お試しください。"
            )
            return
        root.after(0, on_pairing_success, token, server_url)

    def on_start() -> None:
        server_url = server_entry.get().strip()
        if not server_url or server_url == "https://":
            messagebox.showerror("入力エラー", "URLを入力してください。", parent=root)
            return
        start_button.config(state=tk.DISABLED)
        set_status(
            "ブラウザが開きます。ダッシュボードにログインし、"
            "表示されたコードを承認してください..."
        )
        threading.Thread(
            target=run_pairing_in_background, args=(server_url,), daemon=True
        ).start()

    start_button.config(command=on_start)

    root.mainloop()
    return result["value"]
