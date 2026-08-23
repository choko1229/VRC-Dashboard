"""ローカルエージェント（desktop_agent/）からのゲームログ取り込みリクエストのスキーマ。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

GameLogEventType = Literal[
    "instance_join", "instance_leave", "player_join", "player_leave", "video_play"
]


class GameLogEventIn(BaseModel):
    """ローカルエージェントがVRChatのログファイルを解析して生成した1件のイベント。

    event_typeごとに使うフィールドが異なる（他は省略可）。
    - instance_join: location, world_id, world_name
    - instance_leave: (追加情報なし)
    - player_join / player_leave: player_name, player_vrchat_user_id(取得できれば)
    - video_play: detail(再生URL)
    """

    event_type: GameLogEventType
    occurred_at: datetime
    location: str | None = None
    world_id: str | None = None
    world_name: str | None = None
    player_name: str | None = None
    player_vrchat_user_id: str | None = None
    detail: str | None = None


class GameLogIngestRequest(BaseModel):
    events: list[GameLogEventIn]


class DeviceCodeResponse(BaseModel):
    """POST /api/game-log/agent/pair の応答。RFC 8628のdevice authorization responseに準拠。"""

    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class DevicePollRequest(BaseModel):
    device_code: str


class DevicePollResponse(BaseModel):
    # pending: 未承認 / approved: 承認済み(tokenを含む) / denied: 拒否された /
    # expired_or_unknown: 期限切れまたは存在しないdevice_code
    status: Literal["pending", "approved", "denied", "expired_or_unknown"]
    token: str | None = None


class AgentCommandOut(BaseModel):
    """GET /api/agent/commands の1件（デスクトップエージェントへのPC側操作の委譲）。"""

    id: int
    command_type: str
    payload_json: str


class AgentCommandAckRequest(BaseModel):
    status: Literal["done", "failed"]
