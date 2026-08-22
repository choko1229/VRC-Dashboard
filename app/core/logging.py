"""構造化ログ設定。秘密情報は絶対にログへ出さないためのフィルタを含む。"""

from __future__ import annotations

import logging
import re
import sys

# ログレコードの中でこれらのキーに一致する値はマスクする。
_SECRET_KEY_PATTERN = re.compile(
    r"(auth_cookie|two_factor_cookie|authtoken|shared_secret|password|"
    r"client_secret|access_token|refresh_token)",
    re.IGNORECASE,
)
_REDACTED = "***REDACTED***"


class RedactingFilter(logging.Filter):
    """メッセージ・argsの中に秘密情報らしきキー=値が含まれていたらマスクするフィルタ。"""

    _kv_pattern = re.compile(
        rf"({_SECRET_KEY_PATTERN.pattern})\s*[:=]\s*\S+",
        re.IGNORECASE,
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._kv_pattern.sub(rf"\1={_REDACTED}", record.msg)
        if record.args:
            record.args = tuple(
                self._kv_pattern.sub(rf"\1={_REDACTED}", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def configure_logging(*, debug: bool) -> None:
    """アプリ起動時に一度だけ呼び出すログ初期化。"""
    # Windows環境ではstdoutの既定エンコーディングがcp932等になり得るため、
    # 日本語ログが文字化けしないようUTF-8へ明示的に再設定する。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(RedactingFilter())

    root.handlers.clear()
    root.addHandler(handler)

    # ノイズの多い外部ライブラリは抑制
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
