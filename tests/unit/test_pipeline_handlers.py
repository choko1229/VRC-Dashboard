"""フェーズ2: PipelineイベントハンドラのJSONパース〜DB反映のユニットテスト。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.friend import Friend
from app.services.vrchat import pipeline
from tests.fakes import FakeNotificationSender


async def test_on_friend_online_updates_friend(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        content = {
            "userId": "usr_1",
            "user": {"id": "usr_1", "displayName": "Alice"},
            "location": "wrld_abc:12345",
            "world": {"name": "Alice's World"},
        }
        await pipeline._on_friend_online(db, sender, content)

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_1"))
        ).scalar_one()
        assert friend.is_online is True
        assert friend.current_world_name == "Alice's World"


async def test_on_friend_offline_updates_friend(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await pipeline._on_friend_online(
            db, sender, {"userId": "usr_2", "user": {"displayName": "Bob"}}
        )
        await pipeline._on_friend_offline(db, sender, {"userId": "usr_2"})

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_2"))
        ).scalar_one()
        assert friend.is_online is False


async def test_on_friend_location_updates_world(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        content = {
            "userId": "usr_3",
            "displayName": "Carol",
            "location": "wrld_new:999",
            "world": {"name": "New World"},
        }
        await pipeline._on_friend_location(db, sender, content)

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_3"))
        ).scalar_one()
        assert friend.current_world_id == "wrld_new"
        assert friend.current_world_name == "New World"


async def test_on_friend_update_changes_status(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        content = {"user": {"id": "usr_4", "displayName": "Dave", "status": "busy"}}
        await pipeline._on_friend_update(db, sender, content)

        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_4"))
        ).scalar_one()
        assert friend.activity_status == "busy"


async def test_handle_message_dispatches_to_registered_handler(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import json

    manager = pipeline.PipelineManager(
        session_factory=db_session_factory,
        notification_sender_factory=lambda db: _fake_sender_factory(),
        get_auth_cookie=_none_cookie,
        initial_reconnect_seconds=1,
        max_reconnect_seconds=1,
        notify_after_failures=1,
    )
    raw_message = json.dumps(
        {
            "type": "friend-offline",
            "content": json.dumps({"userId": "usr_5", "displayName": "Eve"}),
        }
    )
    await manager._handle_message(raw_message)

    async with db_session_factory() as db:
        friend = (
            await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_5"))
        ).scalar_one()
        assert friend.is_online is False


async def _fake_sender_factory() -> FakeNotificationSender:
    return FakeNotificationSender()


async def _none_cookie() -> str | None:
    return None
