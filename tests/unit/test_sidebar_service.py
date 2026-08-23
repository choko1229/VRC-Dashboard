"""フェーズ7/16: サイドバーのフレンド区分（オンライン(インスタンス別)/アクティブ/オフライン）。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.friend import Friend
from app.services import sidebar_service


async def test_groups_friends_by_state(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        db.add(
            Friend(
                vrchat_user_id="usr_online",
                display_name="Online太郎",
                is_online=True,
                online_state="online",
                current_location="wrld_x:1",
                current_world_name="ワールドX",
            )
        )
        db.add(
            Friend(
                vrchat_user_id="usr_active",
                display_name="Active花子",
                is_online=True,
                online_state="active",
            )
        )
        db.add(
            Friend(
                vrchat_user_id="usr_offline",
                display_name="Offline次郎",
                is_online=False,
                online_state="offline",
            )
        )
        await db.commit()

        groups = await sidebar_service.get_friend_sidebar_groups(db)

        # インスタンスに1人しかいないため、グループの見出しは作らずonline_otherに入る。
        assert groups.instance_groups == []
        assert [f.vrchat_user_id for f in groups.online_other] == ["usr_online"]
        assert [f.vrchat_user_id for f in groups.active] == ["usr_active"]
        assert [f.vrchat_user_id for f in groups.offline] == ["usr_offline"]


async def test_friend_limit_prioritizes_online_over_offline(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.services.sidebar_service import _SIDEBAR_FRIEND_LIMIT

    extra_offline_count = _SIDEBAR_FRIEND_LIMIT + 5

    async with db_session_factory() as db:
        for i in range(extra_offline_count):
            db.add(
                Friend(
                    vrchat_user_id=f"usr_offline_{i}",
                    display_name=f"Z_offline_{i:03d}",
                    is_online=False,
                    online_state="offline",
                )
            )
        db.add(
            Friend(
                vrchat_user_id="usr_online_priority",
                display_name="A_online",
                is_online=True,
                online_state="online",
                current_location="wrld_x:1",
            )
        )
        await db.commit()

        groups = await sidebar_service.get_friend_sidebar_groups(db)

        total_returned = (
            sum(g.friend_count for g in groups.instance_groups)
            + len(groups.online_other)
            + len(groups.active)
            + len(groups.offline)
        )
        assert total_returned == _SIDEBAR_FRIEND_LIMIT
        # 上限を超えても、オンラインのフレンドは切り詰められずに残る
        # (インスタンスに1人しかいないためonline_other側に入る)。
        assert [f.vrchat_user_id for f in groups.online_other] == ["usr_online_priority"]
        assert len(groups.offline) == _SIDEBAR_FRIEND_LIMIT - 1


async def test_groups_friends_by_instance_known_first_unknown_after(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    shared_location = "wrld_shared:99999~friends(usr_self)~region(us)"

    async with db_session_factory() as db:
        db.add(
            Friend(
                vrchat_user_id="usr_same_1",
                display_name="同室A",
                is_online=True,
                online_state="online",
                current_location=shared_location,
                current_world_name="共有ワールド",
            )
        )
        db.add(
            Friend(
                vrchat_user_id="usr_same_2",
                display_name="同室B",
                is_online=True,
                online_state="online",
                current_location=shared_location,
                current_world_name="共有ワールド",
            )
        )
        db.add(
            Friend(
                vrchat_user_id="usr_elsewhere",
                display_name="別室C",
                is_online=True,
                online_state="online",
                current_location="wrld_other:1",
                current_world_name="別のワールド",
            )
        )
        db.add(
            Friend(
                vrchat_user_id="usr_private",
                display_name="非公開D",
                is_online=True,
                online_state="online",
                current_location="private",
            )
        )
        await db.commit()

        groups = await sidebar_service.get_friend_sidebar_groups(db)

        # 2人以上いるインスタンスのみグループ化される。1人だけのインスタンス
        # (usr_elsewhere)とインスタンス不明(usr_private)は、見出し無しの末尾にまとまる。
        assert [g.friend_count for g in groups.instance_groups] == [2]
        assert groups.instance_groups[0].world_name == "共有ワールド"
        assert {f.vrchat_user_id for f in groups.instance_groups[0].friends} == {
            "usr_same_1",
            "usr_same_2",
        }
        assert {f.vrchat_user_id for f in groups.online_other} == {
            "usr_elsewhere",
            "usr_private",
        }
