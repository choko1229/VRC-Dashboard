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


class _FakeWorldLookupClient:
    """`bootstrap_friends_from_vrchat`のワールド名/サムネイル補完に使う最小限のフェイク。"""

    def __init__(
        self, *, world_name: str | None = "テストワールド", thumbnail_url: str | None = None
    ) -> None:
        self._world_name = world_name
        self._thumbnail_url = thumbnail_url
        self.requested_world_ids: list[str] = []

    async def get_world_name(self, world_id: str) -> str | None:
        self.requested_world_ids.append(world_id)
        return self._world_name

    async def get_world_thumbnail_url(self, world_id: str) -> str | None:
        return self._thumbnail_url


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
        client = _FakeWorldLookupClient(
            world_name="テストワールド", thumbnail_url="https://example.com/thumb.png"
        )
        await friends_service.bootstrap_friends_from_vrchat(
            db, client, online_friends=online, offline_friends=offline  # type: ignore[arg-type]
        )

        friends = (await db.execute(select(Friend))).scalars().all()
        by_id = {f.vrchat_user_id: f for f in friends}
        assert by_id["usr_a"].is_online is True
        assert by_id["usr_a"].current_world_id == "wrld_1"
        assert by_id["usr_a"].online_state == "online"
        assert by_id["usr_a"].current_world_name == "テストワールド"
        assert by_id["usr_a"].current_world_thumbnail_url == "https://example.com/thumb.png"
        assert client.requested_world_ids == ["wrld_1"]
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


async def test_status_update_first_sighting_does_not_log_avatar_change(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """アバターURLが未取得(None)から初めて分かった場合は「変更」として記録しない。"""
    async with db_session_factory() as db:
        user = VRChatUser.model_validate(
            {
                "id": "usr_feed1",
                "displayName": "Feed1",
                "status": "active",
                "currentAvatarThumbnailImageUrl": "https://example.com/a.png",
            }
        )
        await friends_service.handle_friend_status_update(db, vrchat_user=user)

        events = (await db.execute(select(FriendPresenceEvent))).scalars().all()
        assert [e.event_type for e in events] == ["status_change"]


async def test_status_update_logs_status_change_with_previous_status(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = Friend(vrchat_user_id="usr_feed2", display_name="Feed2", activity_status="busy")
        db.add(friend)
        await db.commit()

        user = VRChatUser.model_validate(
            {"id": "usr_feed2", "displayName": "Feed2", "status": "join me"}
        )
        await friends_service.handle_friend_status_update(db, vrchat_user=user)

        event = (await db.execute(select(FriendPresenceEvent))).scalars().one()
        assert event.event_type == "status_change"
        assert event.previous_status == "busy"
        assert event.status == "join me"


async def test_status_update_logs_avatar_change_when_url_actually_changes(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = Friend(
            vrchat_user_id="usr_feed3",
            display_name="Feed3",
            activity_status="active",
            current_avatar_thumbnail_url="https://example.com/old.png",
        )
        db.add(friend)
        await db.commit()

        user = VRChatUser.model_validate(
            {
                "id": "usr_feed3",
                "displayName": "Feed3",
                "status": "active",
                "currentAvatarThumbnailImageUrl": "https://example.com/new.png",
            }
        )
        await friends_service.handle_friend_status_update(db, vrchat_user=user)

        events = (await db.execute(select(FriendPresenceEvent))).scalars().all()
        assert [e.event_type for e in events] == ["avatar_change"]


async def test_status_update_no_event_when_nothing_changed(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        friend = Friend(
            vrchat_user_id="usr_feed4",
            display_name="Feed4",
            activity_status="active",
            current_avatar_thumbnail_url="https://example.com/same.png",
        )
        db.add(friend)
        await db.commit()

        user = VRChatUser.model_validate(
            {
                "id": "usr_feed4",
                "displayName": "Feed4",
                "status": "active",
                "currentAvatarThumbnailImageUrl": "https://example.com/same.png",
            }
        )
        await friends_service.handle_friend_status_update(db, vrchat_user=user)

        events = (await db.execute(select(FriendPresenceEvent))).scalars().all()
        assert events == []


def test_group_online_friends_by_instance_groups_by_location_and_sorts_by_size() -> None:
    friend_a1 = Friend(vrchat_user_id="usr_a1", display_name="A1", current_location="wrld_a:1")
    friend_a2 = Friend(vrchat_user_id="usr_a2", display_name="A2", current_location="wrld_a:1")
    friend_a3 = Friend(vrchat_user_id="usr_a3", display_name="A3", current_location="wrld_a:1")
    friend_b1 = Friend(vrchat_user_id="usr_b1", display_name="B1", current_location="wrld_b:1")
    friend_b2 = Friend(vrchat_user_id="usr_b2", display_name="B2", current_location="wrld_b:1")
    friend_alone = Friend(
        vrchat_user_id="usr_alone", display_name="Alone", current_location="wrld_c:1"
    )
    friend_private = Friend(vrchat_user_id="usr_p", display_name="P", current_location="private")
    friend_unknown = Friend(vrchat_user_id="usr_u", display_name="U", current_location=None)

    groups, unknown = friends_service.group_online_friends_by_instance(
        [
            friend_a1,
            friend_a2,
            friend_a3,
            friend_b1,
            friend_b2,
            friend_alone,
            friend_private,
            friend_unknown,
        ]
    )

    # 同じインスタンスに2人以上いるグループのみ見出しを作る(人数の多い順)。
    assert [g.friend_count for g in groups] == [3, 2]
    assert groups[0].location == "wrld_a:1"
    assert groups[0].friends == [friend_a1, friend_a2, friend_a3]
    assert groups[1].location == "wrld_b:1"
    # インスタンスに1人しかいないフレンドはグループの後にまとめるが、現在地が本当に
    # 不明なフレンドより先に表示する（インスタンスがわかっている人を上位にする要件のため）。
    assert unknown == [friend_alone, friend_private, friend_unknown]


def test_group_online_friends_by_instance_uses_first_member_world_info() -> None:
    friend1 = Friend(
        vrchat_user_id="usr_a1",
        display_name="A1",
        current_location="wrld_a:1~region(jp)",
        current_world_name="テストワールド",
        current_world_thumbnail_url="https://example.com/thumb.png",
    )
    friend2 = Friend(
        vrchat_user_id="usr_a2",
        display_name="A2",
        current_location="wrld_a:1~region(jp)",
        current_world_name="テストワールド",
        current_world_thumbnail_url="https://example.com/thumb.png",
    )

    groups, _unknown = friends_service.group_online_friends_by_instance([friend1, friend2])

    assert groups[0].world_name == "テストワールド"
    assert groups[0].world_thumbnail_url == "https://example.com/thumb.png"
    assert groups[0].region_flag == "🇯🇵"


def test_group_online_friends_by_instance_single_member_not_grouped() -> None:
    friend = Friend(vrchat_user_id="usr_alone", display_name="Alone", current_location="wrld_a:1")

    groups, unknown = friends_service.group_online_friends_by_instance([friend])

    assert groups == []
    assert unknown == [friend]
