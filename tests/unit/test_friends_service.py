"""フェーズ2: フレンド状態更新ロジックのユニットテスト。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import SecretCipher
from app.models.friend import Friend
from app.models.friend_group import FriendGroup
from app.models.friend_group_membership import FriendGroupMembership
from app.models.friend_notification_pref import FriendNotificationPref
from app.models.friend_presence_event import FriendPresenceEvent
from app.schemas.vrchat import VRChatFavorite, VRChatFavoriteGroup, VRChatUser
from app.services import friends_service
from tests.fakes import FakeNotificationSender

_TEST_FERNET_KEY = "gdsF_NX-iLtl8QLOwmQyFeEdQtOmWXiAlHD4kTrLuh4="


async def test_handle_friend_online_creates_friend_and_event(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await friends_service.handle_friend_online(
            db,
            sender,
            vrchat_user_id="usr_1",
            display_name="Alice",
            location="wrld_abc:12345",
            world_name="Alice's World",
        )

        result = await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_1"))
        friend = result.scalar_one()
        assert friend.is_online is True
        assert friend.current_world_id == "wrld_abc"
        assert friend.current_world_name == "Alice's World"

        events = (await db.execute(select(FriendPresenceEvent))).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "online"

        # 通知設定が無い（デフォルトOFF）ため送信されない
        assert sender.sent == []


async def test_handle_friend_online_notifies_when_pref_enabled(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = Friend(vrchat_user_id="usr_2", display_name="Bob")
        db.add(friend)
        await db.commit()
        await db.refresh(friend)
        db.add(FriendNotificationPref(friend_id=friend.id, notify_on_online=True))
        await db.commit()

        sender = FakeNotificationSender()
        await friends_service.handle_friend_online(
            db,
            sender,
            vrchat_user_id="usr_2",
            display_name="Bob",
            location=None,
            world_name=None,
        )

        assert len(sender.sent) == 1
        assert sender.sent[0].type == "friend_online"


async def test_handle_friend_offline_clears_world_info(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await friends_service.handle_friend_online(
            db,
            sender,
            vrchat_user_id="usr_3",
            display_name="Carol",
            location="wrld_xyz:1",
            world_name="World",
        )
        await friends_service.handle_friend_offline(
            db, sender, vrchat_user_id="usr_3", display_name="Carol"
        )

        result = await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_3"))
        friend = result.scalar_one()
        assert friend.is_online is False
        assert friend.current_world_id is None
        assert friend.current_world_name is None

        events = (await db.execute(select(FriendPresenceEvent))).scalars().all()
        assert {e.event_type for e in events} == {"online", "offline"}


async def test_handle_friend_active_sets_online_state_without_location(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await friends_service.handle_friend_active(
            db, sender, vrchat_user_id="usr_active", display_name="Dave"
        )

        result = await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_active"))
        friend = result.scalar_one()
        assert friend.is_online is True
        assert friend.online_state == "active"
        assert friend.current_world_id is None
        assert friend.current_location is None


async def test_handle_friend_online_then_offline_updates_online_state(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        sender = FakeNotificationSender()
        await friends_service.handle_friend_online(
            db,
            sender,
            vrchat_user_id="usr_state",
            display_name="Erin",
            location="wrld_a:1",
            world_name="World A",
        )
        result = await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_state"))
        assert result.scalar_one().online_state == "online"

        await friends_service.handle_friend_offline(
            db, sender, vrchat_user_id="usr_state", display_name="Erin"
        )
        result = await db.execute(select(Friend).where(Friend.vrchat_user_id == "usr_state"))
        assert result.scalar_one().online_state == "offline"


async def test_bootstrap_friends_from_vrchat(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        online = [
            VRChatUser.model_validate(
                {
                    "id": "usr_a",
                    "displayName": "A",
                    "status": "active",
                    "state": "online",
                    "location": "wrld_1:1",
                }
            )
        ]
        offline = [
            VRChatUser.model_validate({"id": "usr_b", "displayName": "B", "status": "offline"})
        ]
        await friends_service.bootstrap_friends_from_vrchat(
            db, online_friends=online, offline_friends=offline
        )

        friends = (await db.execute(select(Friend))).scalars().all()
        by_id = {f.vrchat_user_id: f for f in friends}
        assert by_id["usr_a"].is_online is True
        assert by_id["usr_a"].current_world_id == "wrld_1"
        assert by_id["usr_a"].online_state == "online"
        assert by_id["usr_b"].is_online is False
        assert by_id["usr_b"].online_state == "offline"


async def test_sync_favorite_groups_links_memberships(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = Friend(vrchat_user_id="usr_c", display_name="Carl")
        db.add(friend)
        await db.commit()
        await db.refresh(friend)

        groups = [
            VRChatFavoriteGroup(id="grp_1", name="group_0", displayName="親友", type="friend")
        ]
        favorites = [VRChatFavorite(id="fav_1", favorite_id="usr_c", tags=["group_0"])]

        await friends_service.sync_favorite_groups(db, groups=groups, favorites=favorites)

        result = await db.execute(select(FriendGroup).where(FriendGroup.vrchat_group_id == "grp_1"))
        group = result.scalar_one()
        assert group.name == "親友"

        membership = await db.get(FriendGroupMembership, (friend.id, group.id))
        assert membership is not None


async def test_fetch_live_profile_returns_none_without_vrchat_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    async with db_session_factory() as db:
        profile = await friends_service.fetch_live_profile(
            db, cipher, vrchat_user_id="usr_no_session"
        )
        assert profile is None


async def test_fetch_groups_overview_returns_none_without_vrchat_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    async with db_session_factory() as db:
        overview = await friends_service.fetch_groups_overview(
            db, cipher, vrchat_user_id="usr_no_session"
        )
        assert overview is None


async def test_fetch_user_worlds_returns_none_without_vrchat_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    async with db_session_factory() as db:
        worlds = await friends_service.fetch_user_worlds(
            db, cipher, vrchat_user_id="usr_no_session"
        )
        assert worlds is None


async def test_compute_activity_stats_empty_when_no_events(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = Friend(vrchat_user_id="usr_activity", display_name="Activity")
        db.add(friend)
        await db.commit()
        await db.refresh(friend)

        stats = await friends_service.compute_activity_stats(db, friend.id)
        assert stats.total_events == 0
        assert stats.most_active_weekday is None
        assert stats.peak_hour_range is None
        assert stats.max_count == 0


async def test_compute_activity_stats_aggregates_online_events(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from datetime import UTC, datetime

    async with db_session_factory() as db:
        friend = Friend(vrchat_user_id="usr_activity2", display_name="Activity2")
        db.add(friend)
        await db.commit()
        await db.refresh(friend)

        # 2026-08-23 13:00 UTC = 2026-08-23 22:00 JST（日曜日）
        occurred_at = datetime(2026, 8, 23, 13, 0, tzinfo=UTC)
        for _ in range(3):
            db.add(
                FriendPresenceEvent(
                    friend_id=friend.id, event_type="online", occurred_at=occurred_at
                )
            )
        db.add(
            FriendPresenceEvent(
                friend_id=friend.id, event_type="offline", occurred_at=occurred_at
            )
        )
        await db.commit()

        stats = await friends_service.compute_activity_stats(db, friend.id)
        assert stats.total_events == 3
        assert stats.most_active_weekday == "日曜日"
        assert stats.peak_hour_range == "22:00-23:00"
        assert stats.max_count == 3
