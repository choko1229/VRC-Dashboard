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
from http.client import HTTPMessage
from typing import IO

logger = logging.getLogger("gamelog_watcher.device_pairing")

_HTTP_TIMEOUT_SECONDS = 15
_DEFAULT_POLL_INTERVAL_SECONDS = 3
_DEFAULT_EXPIRES_IN_SECONDS = 600


class PairingError(Exception):
    """ペアリング開始に失敗した（サーバーに接続できない、応答が不正 等）。メッセージはUI表示用。"""


class _PreserveMethodRedirectHandler(urllib.request.HTTPRedirectHandler):
    """POSTがリダイレクト先でGETに化けないようにする（既定のurllibはRFC互換のため変換してしまう）。

    http://→https://への強制リダイレクトを設定しているサーバーでもペアリングPOSTが
    正しく届くようにするため。
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        new_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_request is not None:
            new_request.data = req.data
            new_request.method = req.get_method()
        return new_request


_opener = urllib.request.build_opener(_PreserveMethodRedirectHandler)


def normalize_server_url(raw_url: str) -> str:
    """スキームが省略されていれば https:// を補い、末尾のスラッシュを取り除く。"""
    url = raw_url.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            # 既定のUser-Agent（Python-urllib/x.y）はCloudflare等のWAFにボットとして
            # ブロックされることがあるため、明示的に設定する。
            "User-Agent": "VRCDashboardAgent",
        },
    )
    with _opener.open(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
        result: dict[str, object] = json.loads(response.read().decode("utf-8"))
        return result


def start_pairing(server_url: str) -> dict[str, object]:
    """デバイスコードを発行してもらう。device_code/user_code/verification_uri/interval/expires_inを含む。

    失敗した場合、原因を説明するメッセージ付きのPairingErrorを送出する。
    """
    url = server_url.rstrip("/") + "/api/game-log/agent/pair"
    try:
        return _post_json(url, {})
    except urllib.error.HTTPError as exc:
        raise PairingError(
            f"サーバーがエラーを返しました（HTTP {exc.code}）。URLが正しいか、"
            "サーバー側が最新版に更新されているか確認してください。"
        ) from exc
    except urllib.error.URLError as exc:
        raise PairingError(f"サーバーに接続できませんでした: {exc.reason}") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise PairingError("サーバーからの応答を解釈できませんでした。") from exc


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
    """コード発行→ブラウザで承認画面を開く→承認待ち、を一連の流れとして行う。

    サーバーへの接続やペアリング開始に失敗した場合はPairingErrorを送出する（原因が
    メッセージに含まれる）。開始後の拒否/タイムアウトはNoneを返す（正常系の一部のため）。
    """
    normalized_url = normalize_server_url(server_url)
    started = start_pairing(normalized_url)
    try:
        verification_uri = str(started["verification_uri"])
        device_code = str(started["device_code"])
    except KeyError as exc:
        raise PairingError("サーバーからの応答にペアリング情報が含まれていません。") from exc
    interval = _as_int(started.get("interval"), _DEFAULT_POLL_INTERVAL_SECONDS)
    expires_in = _as_int(started.get("expires_in"), _DEFAULT_EXPIRES_IN_SECONDS)

    webbrowser.open(verification_uri)
    return wait_for_approval(
        normalized_url, device_code, interval=interval, expires_in=expires_in
    )
