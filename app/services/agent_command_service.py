"""デスクトップエージェントへのPC側操作委譲キュー（agent_command）の読み書き。

単一ユーザー前提のダッシュボードのため、ユーザー紐付けの無いグローバルな1本のキューとして扱う。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_command import AgentCommand


async def list_pending(db: AsyncSession) -> list[AgentCommand]:
    result = await db.execute(
        select(AgentCommand)
        .where(AgentCommand.status == "pending")
        .order_by(AgentCommand.created_at)
    )
    return list(result.scalars().all())


async def ack(db: AsyncSession, command_id: int, *, status: str) -> bool:
    command = await db.get(AgentCommand, command_id)
    if command is None:
        return False
    command.status = status
    command.completed_at = datetime.now(UTC)
    await db.commit()
    return True
