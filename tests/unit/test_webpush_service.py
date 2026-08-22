"""フェーズ5: Web Push購読管理のユニットテスト。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.dashboard_user import DashboardUser
from app.services import webpush_service


async def test_upsert_subscription_creates_and_updates(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        user = DashboardUser(discord_user_id="1", discord_username="tester")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        await webpush_service.upsert_subscription(
            db,
            dashboard_user_id=user.id,
            endpoint="https://push.example.com/abc",
            p256dh_key="p256dh-1",
            auth_key="auth-1",
            user_agent="TestAgent/1.0",
        )
        subs = await webpush_service.list_subscriptions(db)
        assert len(subs) == 1
        assert subs[0].p256dh_key == "p256dh-1"

        # 同じendpointで再登録すると更新される（重複作成されない）
        await webpush_service.upsert_subscription(
            db,
            dashboard_user_id=user.id,
            endpoint="https://push.example.com/abc",
            p256dh_key="p256dh-2",
            auth_key="auth-2",
            user_agent="TestAgent/2.0",
        )
        subs_after = await webpush_service.list_subscriptions(db)
        assert len(subs_after) == 1
        assert subs_after[0].p256dh_key == "p256dh-2"


async def test_delete_subscription(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        user = DashboardUser(discord_user_id="2", discord_username="tester2")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        await webpush_service.upsert_subscription(
            db,
            dashboard_user_id=user.id,
            endpoint="https://push.example.com/xyz",
            p256dh_key="p256dh",
            auth_key="auth",
            user_agent=None,
        )
        await webpush_service.delete_subscription(db, "https://push.example.com/xyz")
        subs = await webpush_service.list_subscriptions(db)
        assert subs == []
