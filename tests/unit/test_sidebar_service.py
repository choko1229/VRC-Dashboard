"""フェーズ7: サイドバーのフレンド区分（同じインスタンス/オンライン/アクティブ/オフライン）。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import SecretCipher
from app.models.friend import Friend
from app.schemas.vrchat import VRChatInstance
from app.services import sidebar_service, vrchat_session_service
from app.services.vrchat.client import VRChatClient

_TEST_FERNET_KEY = "gdsF_NX-iLtl8QLOwmQyFeEdQtOmWXiAlHD4kTrLuh4="


async def _setup_self_session(
    db: AsyncSession, cipher: SecretCipher, *, self_location: str | None
) -> None:
    await vrchat_session_service.save_session(
        db,
        cipher,
        vrchat_user_id="usr_self",
        vrchat_display_name="Self",
        auth_cookie="dummy-auth-cookie",
        two_factor_cookie=None,
    )
    await vrchat_session_service.update_self_location(
        db, location=self_location, world_id="wrld_shared", world_name="共有ワールド"
    )


async def test_groups_friends_without_self_location(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
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

        groups = await sidebar_service.get_friend_sidebar_groups(db, cipher)

        assert groups.same_instance is None
        assert [f.vrchat_user_id for f in groups.online] == ["usr_online"]
        assert [f.vrchat_user_id for f in groups.active] == ["usr_active"]
        assert [f.vrchat_user_id for f in groups.offline] == ["usr_offline"]


async def test_friend_limit_prioritizes_online_over_offline(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.services.sidebar_service import _SIDEBAR_FRIEND_LIMIT

    cipher = SecretCipher(_TEST_FERNET_KEY)
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

        groups = await sidebar_service.get_friend_sidebar_groups(db, cipher)

        total_returned = (
            len(groups.online)
            + len(groups.active)
            + len(groups.offline)
            + (groups.same_instance.friend_count if groups.same_instance else 0)
        )
        assert total_returned == _SIDEBAR_FRIEND_LIMIT
        # 上限を超えても、オンラインのフレンドは切り詰められずに残る。
        assert [f.vrchat_user_id for f in groups.online] == ["usr_online_priority"]
        assert len(groups.offline) == _SIDEBAR_FRIEND_LIMIT - 1


async def test_groups_same_instance_friends_with_instance_population(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    shared_location = "wrld_shared:99999~friends(usr_self)~region(us)"

    async def fake_get_instance(self: VRChatClient, location: str) -> VRChatInstance:
        assert location == shared_location
        return VRChatInstance(n_users=12)

    monkeypatch.setattr(VRChatClient, "get_instance", fake_get_instance)

    async with db_session_factory() as db:
        await _setup_self_session(db, cipher, self_location=shared_location)

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
        await db.commit()

        groups = await sidebar_service.get_friend_sidebar_groups(db, cipher)

        assert groups.same_instance is not None
        assert groups.same_instance.friend_count == 2
        assert groups.same_instance.instance_total == 12
        assert groups.same_instance.world_name == "共有ワールド"
        assert groups.same_instance.privacy_label == "フレンド+"
        assert {f.vrchat_user_id for f in groups.same_instance.friends} == {
            "usr_same_1",
            "usr_same_2",
        }
        assert [f.vrchat_user_id for f in groups.online] == ["usr_elsewhere"]
