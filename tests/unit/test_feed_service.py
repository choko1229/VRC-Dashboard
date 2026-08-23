"""全フレンド横断アクティビティフィードのユニットテスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.friend import Friend
from app.models.friend_group import FriendGroup
from app.models.friend_group_membership import FriendGroupMembership
from app.models.friend_presence_event import FriendPresenceEvent
from app.services import feed_service


def _dt(minute: int) -> datetime:
    return datetime(2026, 8, 23, 0, minute, 0, tzinfo=UTC)


async def _seed_friend(db: AsyncSession, *, vrchat_user_id: str, display_name: str) -> Friend:
    friend = Friend(vrchat_user_id=vrchat_user_id, display_name=display_name)
    db.add(friend)
    await db.commit()
    await db.refresh(friend)
    return friend


async def test_get_feed_entries_orders_newest_first(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = await _seed_friend(db, vrchat_user_id="usr_a", display_name="Alice")
        db.add(FriendPresenceEvent(friend_id=friend.id, event_type="online", occurred_at=_dt(0)))
        db.add(FriendPresenceEvent(friend_id=friend.id, event_type="offline", occurred_at=_dt(5)))
        await db.commit()

        entries, has_more = await feed_service.get_feed_entries(db)
        assert has_more is False
        assert [e.event.event_type for e in entries] == ["offline", "online"]
        assert entries[0].friend.display_name == "Alice"


async def test_get_feed_entries_filters_by_event_type(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = await _seed_friend(db, vrchat_user_id="usr_a", display_name="Alice")
        db.add(FriendPresenceEvent(friend_id=friend.id, event_type="online", occurred_at=_dt(0)))
        db.add(
            FriendPresenceEvent(
                friend_id=friend.id, event_type="status_change", occurred_at=_dt(1)
            )
        )
        await db.commit()

        entries, _ = await feed_service.get_feed_entries(db, event_type="status_change")
        assert [e.event.event_type for e in entries] == ["status_change"]


async def test_get_feed_entries_ignores_unknown_event_type(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = await _seed_friend(db, vrchat_user_id="usr_a", display_name="Alice")
        db.add(FriendPresenceEvent(friend_id=friend.id, event_type="online", occurred_at=_dt(0)))
        await db.commit()

        # 未知のevent_typeは無視して全件返す（クエリパラメータの不正値対策）。
        entries, _ = await feed_service.get_feed_entries(db, event_type="not-a-real-type")
        assert len(entries) == 1


async def test_get_feed_entries_favorites_only(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        favorite = await _seed_friend(db, vrchat_user_id="usr_fav", display_name="Favorite")
        other = await _seed_friend(db, vrchat_user_id="usr_other", display_name="Other")
        group = FriendGroup(vrchat_group_id="grp_1", name="親友", source="synced")
        db.add(group)
        await db.commit()
        await db.refresh(group)
        db.add(FriendGroupMembership(friend_id=favorite.id, group_id=group.id))
        db.add(FriendPresenceEvent(friend_id=favorite.id, event_type="online", occurred_at=_dt(0)))
        db.add(FriendPresenceEvent(friend_id=other.id, event_type="online", occurred_at=_dt(1)))
        await db.commit()

        entries, _ = await feed_service.get_feed_entries(db, favorites_only=True)
        assert [e.friend.display_name for e in entries] == ["Favorite"]


async def test_get_feed_entries_search_by_display_name(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        alice = await _seed_friend(db, vrchat_user_id="usr_a", display_name="Alice")
        await _seed_friend(db, vrchat_user_id="usr_b", display_name="Bob")
        db.add(FriendPresenceEvent(friend_id=alice.id, event_type="online", occurred_at=_dt(0)))
        await db.commit()

        entries, _ = await feed_service.get_feed_entries(db, search="ali")
        assert [e.friend.display_name for e in entries] == ["Alice"]


async def test_get_feed_entries_pagination(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = await _seed_friend(db, vrchat_user_id="usr_a", display_name="Alice")
        for minute in range(60):
            db.add(
                FriendPresenceEvent(
                    friend_id=friend.id, event_type="online", occurred_at=_dt(minute)
                )
            )
        await db.commit()

        first_page, has_more = await feed_service.get_feed_entries(db, page=0)
        assert len(first_page) == 50
        assert has_more is True

        second_page, has_more = await feed_service.get_feed_entries(db, page=1)
        assert len(second_page) == 10
        assert has_more is False
