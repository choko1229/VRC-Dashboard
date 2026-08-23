"""ブラウザでダッシュボードにログイン→承認、という流れでゲームログ取り込み用トークンを
取得するペアリングフロー（OAuth 2.0 Device Authorization Grantに類似）。標準ライブラリのみ。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
import webbrowser

logger = logging.getLogger("gamelog_watcher.device_pairing")

_HTTP_TIMEOUT_SECONDS = 15
_DEFAULT_POLL_INTERVAL_SECONDS = 3
_DEFAULT_EXPIRES_IN_SECONDS = 600


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
        result: dict[str, object] = json.loads(response.read().decode("utf-8"))
        return result


def start_pairing(server_url: str) -> dict[str, object]:
    """デバイスコードを発行してもらう。device_code/user_code/verification_uri/interval/expires_inを含む。"""
    url = server_url.rstrip("/") + "/api/game-log/agent/pair"
    return _post_json(url, {})


def wait_for_approval(
    server_url: str, device_code: str, *, interval: int, expires_in: int
) -> str | None:
    """承認されるまでポーリングする。承認されればトークンを、拒否/期限切れならNoneを返す。"""
    url = server_url.rstrip("/") + "/api/game-log/agent/pair/poll"
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            result = _post_json(url, {"device_code": device_code})
        except (urllib.error.URLError, ValueError) as exc:
            logger.warning("ペアリング状況の確認に失敗しました: %s", exc)
            continue
        status = result.get("status")
        if status == "approved":
            token = result.get("token")
            return str(token) if token else None
        if status in ("denied", "expired_or_unknown"):
            return None
    return None


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    return default


def pair_with_browser(server_url: str) -> str | None:
    """コード発行→ブラウザで承認画面を開く→承認待ち、を一連の流れとして行う。"""
    started = start_pairing(server_url)
    verification_uri = str(started["verification_uri"])
    device_code = str(started["device_code"])
    interval = _as_int(started.get("interval"), _DEFAULT_POLL_INTERVAL_SECONDS)
    expires_in = _as_int(started.get("expires_in"), _DEFAULT_EXPIRES_IN_SECONDS)

    webbrowser.open(verification_uri)
    return wait_for_approval(server_url, device_code, interval=interval, expires_in=expires_in)
