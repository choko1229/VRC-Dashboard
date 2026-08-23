"""ダッシュボードからのPC側操作の委譲（例: VRChatを起動してインスタンスに参加する）を
ポーリングする。

VRChatの「招待を承諾する」等、実際にVRChatクライアントを起動する必要があるアクションは
サーバー単体では実行できないため、ダッシュボード側の通知ページで操作された結果を
agent_commandキューに積んでおき、このエージェントが定期的に取りに行って実行する。

desktop_agent/gamelog_watcher.py と同じ流儀（標準ライブラリのみ、urllib.request、
同じAuthorization/User-Agentヘッダー）で実装する。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("gamelog_watcher.command_poller")

_DEFAULT_POLL_INTERVAL_SECONDS = 5.0


def fetch_pending_commands(server_url: str, api_key: str) -> list[dict[str, Any]]:
    url = server_url.rstrip("/") + "/api/agent/commands"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "VRCDashboardAgent",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            loaded = json.loads(response.read())
            return loaded if isinstance(loaded, list) else []
    except (urllib.error.URLError, ValueError) as exc:
        logger.warning("コマンドの取得に失敗しました（次回リトライします）: %s", exc)
        return []


def ack_command(server_url: str, api_key: str, command_id: int, *, status: str) -> None:
    url = server_url.rstrip("/") + f"/api/agent/commands/{command_id}/ack"
    body = json.dumps({"status": status}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "VRCDashboardAgent",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except urllib.error.URLError as exc:
        logger.warning("コマンドの完了報告に失敗しました: %s", exc)


def _execute(command: dict[str, Any]) -> bool:
    command_type = command.get("command_type")
    if command_type == "join_instance":
        try:
            payload = json.loads(command.get("payload_json", "{}"))
        except ValueError:
            logger.warning("コマンドのpayloadが不正です: %s", command)
            return False
        location = payload.get("location")
        if not isinstance(location, str) or not location:
            logger.warning("join_instanceにlocationがありません: %s", command)
            return False
        logger.info("VRChatを起動してインスタンスに参加します: %s", location)
        os.startfile(f"vrchat://launch?id={location}")
        return True

    logger.warning("未対応のコマンド種別です: %s", command_type)
    return False


def poll_and_execute(server_url: str, api_key: str) -> None:
    for command in fetch_pending_commands(server_url, api_key):
        command_id = command.get("id")
        if not isinstance(command_id, int):
            continue
        succeeded = _execute(command)
        ack_command(server_url, api_key, command_id, status="done" if succeeded else "failed")


def run_forever(
    server_url: str, api_key: str, *, poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS
) -> None:
    logger.info("PC側操作コマンドのポーリングを開始します")
    while True:
        try:
            poll_and_execute(server_url, api_key)
        except Exception:
            logger.exception("コマンドポーリングで予期しないエラーが発生しました")
        time.sleep(poll_interval_seconds)
