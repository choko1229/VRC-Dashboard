"""ブラウザのWeb Push購読情報の管理。"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.web_push_subscription import WebPushSubscription


async def upsert_subscription(
    db: AsyncSession,
    *,
    dashboard_user_id: int,
    endpoint: str,
    p256dh_key: str,
    auth_key: str,
    user_agent: str | None,
) -> None:
    result = await db.execute(
        select(WebPushSubscription).where(WebPushSubscription.endpoint == endpoint)
    )
    row = result.scalar_one_or_none()
    if row is None:
        db.add(
            WebPushSubscription(
                dashboard_user_id=dashboard_user_id,
                endpoint=endpoint,
                p256dh_key=p256dh_key,
                auth_key=auth_key,
                user_agent=user_agent,
            )
        )
    else:
        row.p256dh_key = p256dh_key
        row.auth_key = auth_key
        row.user_agent = user_agent
    await db.commit()


async def delete_subscription(db: AsyncSession, endpoint: str) -> None:
    await db.execute(
        delete(WebPushSubscription).where(WebPushSubscription.endpoint == endpoint)
    )
    await db.commit()


async def list_subscriptions(db: AsyncSession) -> list[WebPushSubscription]:
    result = await db.execute(select(WebPushSubscription))
    return list(result.scalars().all())
