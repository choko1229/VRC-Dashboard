"""フェーズ7c: フレンド一覧のタブ切替（オンライン/お気に入り/アクティブ/オフライン）と
検索・並び順（オフラインを最後に回す）の結合テスト。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_current_user
from app.models.dashboard_user import DashboardUser
from app.models.friend import Friend
from app.models.friend_group import FriendGroup
from app.models.friend_group_membership import FriendGroupMembership


def _login(fastapi_app: FastAPI) -> None:
    async def fake_current_user() -> DashboardUser:
        return DashboardUser(
            id=1,
            discord_user_id="1",
            discord_username="tester",
            is_admin=False,
            first_login_at=datetime.now(UTC),
            last_login_at=datetime.now(UTC),
        )

    fastapi_app.dependency_overrides[get_current_user] = fake_current_user


async def _seed_friends(db_session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with db_session_factory() as db:
        db.add(
            Friend(
                vrchat_user_id="usr_online",
                display_name="オンライン花子",
                is_online=True,
                online_state="online",
                current_world_name="ワールドA",
                current_location="wrld_a:1",
            )
        )
        db.add(
            Friend(
                vrchat_user_id="usr_active",
                display_name="アクティブ太郎",
                is_online=True,
                online_state="active",
            )
        )
        db.add(
            Friend(
                vrchat_user_id="usr_offline",
                display_name="オフライン次郎",
                is_online=False,
                online_state="offline",
            )
        )
        db.add(Friend(vrchat_user_id="usr_fav", display_name="お気に入り三郎", is_online=False))
        await db.commit()

        group = FriendGroup(name="親友", source="local")
        db.add(group)
        await db.commit()
        await db.refresh(group)

        friend_id = await select_friend(db, "usr_fav")
        db.add(FriendGroupMembership(friend_id=friend_id, group_id=group.id))
        await db.commit()


async def select_friend(db: AsyncSession, vrchat_user_id: str) -> int:
    result = await db.execute(select(Friend.id).where(Friend.vrchat_user_id == vrchat_user_id))
    return result.scalar_one()


async def test_online_tab_shows_only_online_state_friends(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _login(fastapi_app)
    await _seed_friends(db_session_factory)

    response = await client.get("/friends/partials/list", params={"filter_tab": "online"})

    assert response.status_code == 200
    assert "オンライン花子" in response.text
    assert "アクティブ太郎" not in response.text
    assert "オフライン次郎" not in response.text


async def test_active_tab_shows_only_active_friends(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _login(fastapi_app)
    await _seed_friends(db_session_factory)

    response = await client.get("/friends/partials/list", params={"filter_tab": "active"})

    assert response.status_code == 200
    assert "アクティブ太郎" in response.text
    assert "オンライン花子" not in response.text


async def test_offline_tab_shows_only_offline_friends(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _login(fastapi_app)
    await _seed_friends(db_session_factory)

    response = await client.get("/friends/partials/list", params={"filter_tab": "offline"})

    assert response.status_code == 200
    assert "オフライン次郎" in response.text
    assert "オンライン花子" not in response.text


async def test_favorites_tab_shows_group_members_regardless_of_state(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _login(fastapi_app)
    await _seed_friends(db_session_factory)

    response = await client.get("/friends/partials/list", params={"filter_tab": "favorites"})

    assert response.status_code == 200
    assert "お気に入り三郎" in response.text
    assert "オンライン花子" not in response.text


async def test_search_filters_by_display_name(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _login(fastapi_app)
    await _seed_friends(db_session_factory)

    response = await client.get(
        "/friends/partials/list", params={"filter_tab": "online", "q": "花子"}
    )

    assert response.status_code == 200
    assert "オンライン花子" in response.text


async def test_offline_sorts_last_within_favorites_tab(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _login(fastapi_app)
    async with db_session_factory() as db:
        db.add(
            Friend(
                vrchat_user_id="usr_fav_online",
                display_name="A_オンライン",
                is_online=True,
                online_state="online",
            )
        )
        db.add(
            Friend(
                vrchat_user_id="usr_fav_offline",
                display_name="Z_オフライン",
                is_online=False,
                online_state="offline",
            )
        )
        await db.commit()
        group = FriendGroup(name="G", source="local")
        db.add(group)
        await db.commit()
        await db.refresh(group)
        for vrchat_user_id in ("usr_fav_online", "usr_fav_offline"):
            friend_id = await select_friend(db, vrchat_user_id)
            db.add(FriendGroupMembership(friend_id=friend_id, group_id=group.id))
        await db.commit()

    response = await client.get("/friends/partials/list", params={"filter_tab": "favorites"})
    text = response.text
    assert text.index("A_オンライン") < text.index("Z_オフライン")
