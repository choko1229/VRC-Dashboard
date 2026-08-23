"""ローカルエージェント（local_agent/）からのゲームログ取り込みリクエストのスキーマ。"""

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
