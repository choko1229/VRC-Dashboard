"""VRChatのローカルログを監視し、ダッシュボードへゲームログイベントを送信するエージェント。

VRChatを起動しているPC上で常駐させて使う。ダッシュボード本体（サーバー側）とは別プロセス・
別マシンで動く想定のため、標準ライブラリのみで動作する（pipインストール不要）。

使い方:
    python gamelog_watcher.py --server-url https://your-dashboard.example.com \
        --api-key <発行したキー>

設定を毎回引数で渡したくない場合は、このスクリプトと同じディレクトリに
gamelog_agent_config.json を置くと読み込む（--config で場所を変更可能）。
    {
        "server_url": "https://your-dashboard.example.com",
        "api_key": "..."
    }

VRChatのログ書式は非公式であり将来変わる可能性がある。実際の環境で動作確認のうえ、
gamelog_parser.py の正規表現を必要に応じて調整すること。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from local_agent.gamelog_parser import (  # noqa: E402
    ParsedEvent,
    parse_line,
    world_id_from_location,
)

# Windowsのコンソールは既定でUTF-8でないことがあり、日本語ログが文字化けするため明示する。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gamelog_watcher")

_DEFAULT_FLUSH_INTERVAL_SECONDS = 5.0
_DEFAULT_POLL_INTERVAL_SECONDS = 1.0
_MAX_BUFFERED_EVENTS = 5000
_DEFAULT_STATE_FILE = Path(__file__).resolve().parent / "gamelog_agent_state.json"
_DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent / "gamelog_agent_config.json"


def default_log_dir() -> Path:
    user_profile = os.environ.get("USERPROFILE", str(Path.home()))
    return Path(user_profile) / "AppData" / "LocalLow" / "VRChat" / "VRChat"


def find_latest_log_file(log_dir: Path) -> Path | None:
    candidates = sorted(
        log_dir.glob("output_log_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return candidates[0] if candidates else None


def load_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        loaded: dict[str, Any] = json.loads(state_file.read_text(encoding="utf-8"))
        return loaded
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state_file: Path, *, file_path: str, offset: int) -> None:
    state_file.write_text(
        json.dumps({"file": file_path, "offset": offset}), encoding="utf-8"
    )


def load_config(config_file: Path) -> dict[str, str]:
    if not config_file.exists():
        return {}
    try:
        loaded: dict[str, str] = json.loads(config_file.read_text(encoding="utf-8"))
        return loaded
    except (json.JSONDecodeError, OSError):
        return {}


def event_to_payload(event: ParsedEvent) -> dict[str, Any]:
    """occurred_atをローカルタイムゾーン付きISO8601に変換してJSON送信用の辞書にする。"""
    aware_occurred_at = event.occurred_at.astimezone()
    return {
        "event_type": event.event_type,
        "occurred_at": aware_occurred_at.isoformat(),
        "location": event.location,
        "world_id": world_id_from_location(event.location) if event.location else None,
        "world_name": event.world_name,
        "player_name": event.player_name,
        "player_vrchat_user_id": event.player_vrchat_user_id,
        "detail": event.detail,
    }


def send_events(server_url: str, api_key: str, events: list[dict[str, Any]]) -> bool:
    if not events:
        return True
    url = server_url.rstrip("/") + "/api/game-log/events"
    body = json.dumps({"events": events}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
            return bool(200 <= response.status < 300)
    except urllib.error.URLError as exc:
        logger.warning("送信に失敗しました（次回リトライします）: %s", exc)
        return False


class GameLogWatcher:
    """ログファイルをtailし、パース済みイベントをバッファリングして定期送信する。"""

    def __init__(
        self,
        *,
        server_url: str,
        api_key: str,
        log_dir: Path,
        state_file: Path,
        flush_interval_seconds: float = _DEFAULT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._server_url = server_url
        self._api_key = api_key
        self._log_dir = log_dir
        self._state_file = state_file
        self._flush_interval_seconds = flush_interval_seconds

        self._current_file: Path | None = None
        self._read_offset = 0
        self._committed_offset = 0
        self._pending_join: ParsedEvent | None = None
        self._buffer: list[dict[str, Any]] = []
        self._last_flush_at = time.monotonic()

    def _enqueue(self, event: ParsedEvent) -> None:
        self._buffer.append(event_to_payload(event))
        if len(self._buffer) > _MAX_BUFFERED_EVENTS:
            dropped = len(self._buffer) - _MAX_BUFFERED_EVENTS
            self._buffer = self._buffer[dropped:]
            logger.warning(
                "サーバーへの送信が長時間失敗しているため、古いイベント%d件を破棄しました", dropped
            )

    def _flush_pending_join(self) -> None:
        if self._pending_join is not None:
            self._enqueue(self._pending_join)
            self._pending_join = None

    def _handle_parsed_event(self, parsed: ParsedEvent) -> None:
        if parsed.event_type == "instance_join":
            self._flush_pending_join()
            self._pending_join = parsed
            return
        if parsed.event_type == "world_name":
            if self._pending_join is not None:
                self._pending_join.world_name = parsed.world_name
                self._flush_pending_join()
            return
        self._flush_pending_join()
        self._enqueue(parsed)

    def _open_next_file(self) -> bool:
        """新しいログファイルへの切り替えが必要なら切り替える。切り替えたらTrueを返す。"""
        latest = find_latest_log_file(self._log_dir)
        if latest is None:
            return False
        if self._current_file is not None and latest == self._current_file:
            return False

        self._flush_pending_join()
        state = load_state(self._state_file) if self._current_file is None else {}
        if state.get("file") == str(latest):
            offset = int(state.get("offset", 0))
        else:
            # 初めて見るファイルは過去分を読み込まず、末尾から追跡を始める。
            offset = latest.stat().st_size
        self._current_file = latest
        self._read_offset = offset
        self._committed_offset = offset
        logger.info("ログファイルを追跡します: %s (offset=%d)", latest, offset)
        return True

    def _read_new_lines(self) -> list[str]:
        if self._current_file is None or not self._current_file.exists():
            return []
        with self._current_file.open("r", encoding="utf-8", errors="replace") as fp:
            fp.seek(self._read_offset)
            lines = fp.readlines()
            self._read_offset = fp.tell()
        return lines

    def _flush(self) -> None:
        if not self._buffer:
            self._last_flush_at = time.monotonic()
            return
        if send_events(self._server_url, self._api_key, self._buffer):
            self._buffer.clear()
            self._committed_offset = self._read_offset
            if self._current_file is not None:
                save_state(
                    self._state_file,
                    file_path=str(self._current_file),
                    offset=self._committed_offset,
                )
        self._last_flush_at = time.monotonic()

    def run_forever(self, *, poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        logger.info("監視を開始します（ログディレクトリ: %s）", self._log_dir)
        while True:
            self._open_next_file()
            for line in self._read_new_lines():
                parsed = parse_line(line)
                if parsed is not None:
                    self._handle_parsed_event(parsed)

            if time.monotonic() - self._last_flush_at >= self._flush_interval_seconds:
                self._flush()

            time.sleep(poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", help="ダッシュボードのURL（例: https://vrc.example.com）")
    parser.add_argument("--api-key", help="/game-logのエージェント連携設定で発行したAPIキー")
    parser.add_argument("--log-dir", help="VRChatのログディレクトリ（省略時は標準の場所）")
    parser.add_argument(
        "--config", default=str(_DEFAULT_CONFIG_FILE), help="設定JSONファイルのパス"
    )
    parser.add_argument("--state-file", default=str(_DEFAULT_STATE_FILE))
    parser.add_argument("--flush-interval", type=float, default=_DEFAULT_FLUSH_INTERVAL_SECONDS)
    args = parser.parse_args()

    config = load_config(Path(args.config))
    server_url = args.server_url or config.get("server_url")
    api_key = args.api_key or config.get("api_key")
    if not server_url or not api_key:
        parser.error(
            "server_urlとapi_keyが必要です。--server-url/--api-keyを指定するか、"
            f"{args.config} に設定してください。"
        )

    log_dir = Path(args.log_dir) if args.log_dir else default_log_dir()
    if not log_dir.exists():
        logger.warning("ログディレクトリが見つかりません: %s", log_dir)

    watcher = GameLogWatcher(
        server_url=server_url,
        api_key=api_key,
        log_dir=log_dir,
        state_file=Path(args.state_file),
        flush_interval_seconds=args.flush_interval,
    )
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        logger.info("停止しました")


if __name__ == "__main__":
    main()
