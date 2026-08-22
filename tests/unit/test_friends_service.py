"""フェーズ2: フレンド状態更新ロジックのユニットテスト。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.friend import Friend
from app.models.friend_group import FriendGroup
from app.models.friend_group_membership import FriendGroupMembership
from app.models.friend_notification_pref import FriendNotificationPref
from app.models.friend_presence_event import FriendPresenceEvent
from app.schemas.vrchat import VRChatFavorite, VRChatFavoriteGroup, VRChatUser
from app.services import friends_service
from tests.fakes import FakeNotificationSender


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


async def test_bootstrap_friends_from_vrchat(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        online = [
            VRChatUser.model_validate(
                {"id": "usr_a", "displayName": "A", "status": "active", "location": "wrld_1:1"}
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
        assert by_id["usr_b"].is_online is False


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
