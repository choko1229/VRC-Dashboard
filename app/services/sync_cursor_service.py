"""REST同期の最終実行状況(sync_cursor)の記録。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync_cursor import SyncCursor


async def mark_synced(
    db: AsyncSession, resource_name: str, *, success: bool, error: str | None = None
) -> None:
    cursor = await db.get(SyncCursor, resource_name)
    if cursor is None:
        cursor = SyncCursor(resource_name=resource_name)
        db.add(cursor)

    cursor.last_synced_at = datetime.now(UTC)
    cursor.last_success = success
    cursor.last_error = error
    await db.commit()
