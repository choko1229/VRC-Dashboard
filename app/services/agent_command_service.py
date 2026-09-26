"""デスクトップエージェントへのPC側操作委譲キュー（agent_command）の読み書き。

複数人利用のため、ダッシュボードユーザーごとのキューとして扱う（エージェントは自分のトークンの
所有者宛てのコマンドだけを受け取る）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_command import AgentCommand


async def list_pending(db: AsyncSession, user_id: int) -> list[AgentCommand]:
    result = await db.execute(
        select(AgentCommand)
        .where(AgentCommand.dashboard_user_id == user_id, AgentCommand.status == "pending")
        .order_by(AgentCommand.created_at)
    )
    return list(result.scalars().all())


async def ack(db: AsyncSession, user_id: int, command_id: int, *, status: str) -> bool:
    command = await db.get(AgentCommand, command_id)
    if command is None or command.dashboard_user_id != user_id:
        return False
    command.status = status
    command.completed_at = datetime.now(UTC)
    await db.commit()
    return True
