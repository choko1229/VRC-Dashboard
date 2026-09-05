"""デスクトップエージェントのゲームログ取り込み用トークン（複数デバイス対応）の発行・検証。

旧: app_settingに単一のAPIキーハッシュを1個だけ保持する方式だった（generate_game_log_api_key等）。
新しいデバイスをペアリングするたびに既存デバイスのトークンを無効化してしまわないよう、
game_log_agent_tokenテーブルで複数トークンを管理する方式に置き換えた。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_session_token
from app.models.game_log_agent_token import GameLogAgentToken

# デスクトップエージェントは/api/agent/commandsを5秒間隔で常時ポーリングしており
# （require_game_log_api_key経由でverify_tokenが呼ばれ、last_used_atが更新される）、
# これを事実上のハートビートとして使う。PCのスリープ/シャットダウン等でエージェントごと
# 応答が途絶えた場合、進行中インスタンスの経過時間表示が「今」まで際限なく伸び続けないよう、
# この閾値を超えて疎通が無ければ最終疎通時刻を上限として扱う。
_STALE_THRESHOLD = timedelta(minutes=2)


async def create_token(db: AsyncSession, *, label: str | None = None) -> str:
    """新しいトークンを発行する。生の値はこの戻り値でしか得られない（DBにはハッシュのみ保存）。"""
    raw_token = secrets.token_urlsafe(32)
    db.add(GameLogAgentToken(token_hash=hash_session_token(raw_token), label=label))
    await db.commit()
    return raw_token


async def list_tokens(db: AsyncSession) -> list[GameLogAgentToken]:
    result = await db.execute(select(GameLogAgentToken).order_by(GameLogAgentToken.created_at))
    return list(result.scalars().all())


async def revoke_token(db: AsyncSession, token_id: int) -> None:
    await db.execute(delete(GameLogAgentToken).where(GameLogAgentToken.id == token_id))
    await db.commit()


async def verify_token(db: AsyncSession, raw_token: str) -> bool:
    """トークンを検証し、有効なら最終利用時刻を更新してTrueを返す。"""
    token_hash = hash_session_token(raw_token)
    result = await db.execute(
        select(GameLogAgentToken).where(GameLogAgentToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()
    if token is None:
        return False
    token.last_used_at = datetime.now(UTC)
    await db.commit()
    return True


async def any_token_configured(db: AsyncSession) -> bool:
    result = await db.execute(select(GameLogAgentToken.id).limit(1))
    return result.scalar_one_or_none() is not None


async def get_effective_now(db: AsyncSession) -> datetime:
    """進行中インスタンスの経過時間表示に使う「今」。

    どのエージェントからも_STALE_THRESHOLDを超えて疎通が無ければ、実時刻の代わりに
    最終疎通時刻を返す（PCのスリープ/シャットダウン等で退出イベントが送れなくなった場合の
    保険。根本原因側の対策はdesktop_agent/gamelog_watcher.pyのVRChatプロセス生死監視）。
    """
    now = datetime.now(UTC)
    result = await db.execute(select(func.max(GameLogAgentToken.last_used_at)))
    last_heartbeat = result.scalar_one_or_none()
    if last_heartbeat is None:
        return now
    last_heartbeat_aware = (
        last_heartbeat if last_heartbeat.tzinfo is not None else last_heartbeat.replace(tzinfo=UTC)
    )
    if now - last_heartbeat_aware > _STALE_THRESHOLD:
        return last_heartbeat_aware
    return now
