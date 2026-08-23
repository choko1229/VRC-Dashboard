"""エージェントの設定（ダッシュボードURL・APIキー）の読み書き。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from desktop_agent.paths import config_file


@dataclass
class AgentConfig:
    server_url: str
    api_key: str


def load_config() -> AgentConfig | None:
    path = config_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AgentConfig(server_url=str(data["server_url"]), api_key=str(data["api_key"]))
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def save_config(config: AgentConfig) -> None:
    config_file().write_text(
        json.dumps({"server_url": config.server_url, "api_key": config.api_key}),
        encoding="utf-8",
    )
