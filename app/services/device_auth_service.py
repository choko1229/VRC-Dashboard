"""デスクトップエージェントの「ブラウザでログイン→承認」ペアリングフロー。

OAuth 2.0 Device Authorization Grant（RFC 8628）に似た方式:
1. エージェントが`POST /api/game-log/agent/pair`でペアリングコード一式を取得する。
2. エージェントはverification_uri（コード入り）を既定のブラウザで開く。
3. ダッシュボードに管理者としてログイン中のユーザーがコードを確認して承認する
   （`POST /game-log/device/approve`）。承認するとgame_log_agent_tokenが新規発行される。
4. エージェントは`POST /api/game-log/agent/pair/poll`を数秒おきに叩き、承認されたら
   発行されたトークンを受け取って以降の`POST /api/game-log/events`等の認証に使う。

ペアリングコードは短命（有効期限10分）でプロセス再起動をまたいで保持する必要が無いため、
DBではなくメモリ上で管理する（本アプリはシングルプロセス運用前提。app.services.sidebar_service
の同時接続インスタンス人数キャッシュと同じ考え方）。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import game_log_agent_token_service

CODE_TTL_SECONDS = 600
POLL_INTERVAL_SECONDS = 3

DeviceCodeStatus = Literal["pending", "approved", "denied"]

# まぎらわしい文字（0/O、1/I）を除いたアルファベット。
_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass
class DeviceCodeEntry:
    device_code: str
    user_code: str
    created_at: float
    status: DeviceCodeStatus = "pending"
    issued_token: str | None = None


_entries: dict[str, DeviceCodeEntry] = {}


def _generate_user_code() -> str:
    def block() -> str:
        return "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(4))

    return f"{block()}-{block()}"


def _cleanup_expired() -> None:
    now = time.time()
    expired = [
        code for code, entry in _entries.items() if now - entry.created_at > CODE_TTL_SECONDS
    ]
    for code in expired:
        del _entries[code]


def create_device_code() -> DeviceCodeEntry:
    _cleanup_expired()
    entry = DeviceCodeEntry(
        device_code=secrets.token_urlsafe(24),
        user_code=_generate_user_code(),
        created_at=time.time(),
    )
    _entries[entry.device_code] = entry
    return entry


def find_by_user_code(user_code: str) -> DeviceCodeEntry | None:
    _cleanup_expired()
    normalized = user_code.strip().upper()
    for entry in _entries.values():
        if entry.user_code == normalized and entry.status == "pending":
            return entry
    return None


async def approve(db: AsyncSession, user_code: str, *, label: str | None = None) -> bool:
    entry = find_by_user_code(user_code)
    if entry is None:
        return False
    raw_token = await game_log_agent_token_service.create_token(db, label=label)
    entry.status = "approved"
    entry.issued_token = raw_token
    return True


def deny(user_code: str) -> bool:
    entry = find_by_user_code(user_code)
    if entry is None:
        return False
    entry.status = "denied"
    return True


def poll(device_code: str) -> DeviceCodeEntry | None:
    _cleanup_expired()
    return _entries.get(device_code)
