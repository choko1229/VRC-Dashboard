"""VRChatクライアントのローカルログ（output_log_*.txt）1行を解析するロジック。

VRChatのログ書式は非公式かつ将来のクライアント更新で変わりうる。ここでの正規表現は
VRCX等の既存コミュニティツールで広く知られているパターンに基づく最善努力の実装であり、
実際の環境のログで動作確認・調整が必要になる場合がある（README参照）。

このモジュールは標準ライブラリのみに依存する（ローカルエージェントは本体アプリの
Python環境とは別のPC上で、追加のpipインストール無しに動かせることを優先しているため）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_TIMESTAMP_RE = re.compile(r"^(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})")
_JOINING_INSTANCE_RE = re.compile(r"\[Behaviour\] Joining (wrld_[0-9a-fA-F-]+:\S+)")
_JOINING_ROOM_NAME_RE = re.compile(r"\[Behaviour\] Joining or Creating Room: (.+)$")
_LEFT_ROOM_RE = re.compile(r"\[Behaviour\] OnLeftRoom")
_PLAYER_JOINED_RE = re.compile(
    r"\[Behaviour\] OnPlayerJoined (.+?)(?:\s+\((usr_[0-9a-fA-F-]+)\))?$"
)
_PLAYER_LEFT_RE = re.compile(
    r"\[Behaviour\] OnPlayerLeft (.+?)(?:\s+\((usr_[0-9a-fA-F-]+)\))?$"
)
_VIDEO_URL_RE = re.compile(
    r"(?:\[Video Playback\]|USharpVideo|VideoPlayer).*?(https?://\S+)", re.IGNORECASE
)

# instance_join / instance_leave / player_join / player_leave / video_play / world_name
ParsedEventType = str


@dataclass
class ParsedEvent:
    """ログ1行から得られたイベント。

    event_type="world_name" はサーバー送信用のスキーマには存在しない中間表現で、
    直前のinstance_joinイベントにワールド名をマージするために使う
    （VRChatのログは「Joining <location>」の次の行で「Joining or Creating Room: <名前>」
    が出力されるため）。
    """

    event_type: ParsedEventType
    occurred_at: datetime
    location: str | None = None
    world_name: str | None = None
    player_name: str | None = None
    player_vrchat_user_id: str | None = None
    detail: str | None = None


def parse_timestamp(line: str) -> datetime | None:
    match = _TIMESTAMP_RE.match(line)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y.%m.%d %H:%M:%S")


def parse_line(line: str) -> ParsedEvent | None:
    """ログ1行を解析する。認識できない行や既知イベントでない行はNoneを返す。"""
    timestamp = parse_timestamp(line)
    if timestamp is None:
        return None

    match = _JOINING_INSTANCE_RE.search(line)
    if match:
        return ParsedEvent(
            event_type="instance_join", occurred_at=timestamp, location=match.group(1)
        )

    match = _JOINING_ROOM_NAME_RE.search(line)
    if match:
        return ParsedEvent(
            event_type="world_name", occurred_at=timestamp, world_name=match.group(1).strip()
        )

    if _LEFT_ROOM_RE.search(line):
        return ParsedEvent(event_type="instance_leave", occurred_at=timestamp)

    match = _PLAYER_JOINED_RE.search(line)
    if match:
        return ParsedEvent(
            event_type="player_join",
            occurred_at=timestamp,
            player_name=match.group(1).strip(),
            player_vrchat_user_id=match.group(2),
        )

    match = _PLAYER_LEFT_RE.search(line)
    if match:
        return ParsedEvent(
            event_type="player_leave",
            occurred_at=timestamp,
            player_name=match.group(1).strip(),
            player_vrchat_user_id=match.group(2),
        )

    match = _VIDEO_URL_RE.search(line)
    if match:
        url = match.group(1).rstrip("'\",)")
        return ParsedEvent(event_type="video_play", occurred_at=timestamp, detail=url)

    return None


def world_id_from_location(location: str) -> str | None:
    """"wrld_xxxx:12345~region(jp)" 形式のlocationからワールドIDを取り出す。"""
    world_id = location.split(":", 1)[0]
    return world_id or None
