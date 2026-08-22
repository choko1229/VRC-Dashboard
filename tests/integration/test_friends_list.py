"""フェーズ7d: フレンド一覧の「お気に入り/オンライン/オフライン」区分と、
フレンド詳細モーダル用エンドポイントの結合テスト。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
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


async def _add_to_group(db: AsyncSession, vrchat_user_id: str, group_name: str) -> None:
    from sqlalchemy import select

    group_result = await db.execute(select(FriendGroup).where(FriendGroup.name == group_name))
    group = group_result.scalar_one_or_none()
    if group is None:
        group = FriendGroup(name=group_name, source="local")
        db.add(group)
        await db.commit()
        await db.refresh(group)

    friend_result = await db.execute(
        select(Friend.id).where(Friend.vrchat_user_id == vrchat_user_id)
    )
    friend_id = friend_result.scalar_one()
    db.add(FriendGroupMembership(friend_id=friend_id, group_id=group.id))
    await db.commit()


async def test_friends_page_shows_online_and_offline_sections(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _login(fastapi_app)
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
                vrchat_user_id="usr_offline",
                display_name="オフライン次郎",
                is_online=False,
                online_state="offline",
            )
        )
        await db.commit()

    response = await client.get("/friends")

    assert response.status_code == 200
    assert "オンライン花子" in response.text
    assert "オフライン次郎" in response.text
    assert "オフライン — 1" in response.text


async def test_favorite_friend_shown_only_in_favorites_section_even_if_offline(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _login(fastapi_app)
    async with db_session_factory() as db:
        db.add(
            Friend(
                vrchat_user_id="usr_fav_offline",
                display_name="お気に入りオフライン",
                is_online=False,
                online_state="offline",
            )
        )
        await db.commit()
        await _add_to_group(db, "usr_fav_offline", "親友")

    response = await client.get("/friends")

    assert response.status_code == 200
    assert "お気に入り — 1" in response.text
    # お気に入り区分にのみ表示され、オフライン区分には重複表示されない。
    assert response.text.count("お気に入りオフライン") == 1
    assert "オフライン — " not in response.text


async def test_friend_detail_modal_returns_bare_fragment(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _login(fastapi_app)
    async with db_session_factory() as db:
        db.add(Friend(vrchat_user_id="usr_modal", display_name="モーダル太郎", is_online=False))
        await db.commit()
        from sqlalchemy import select

        friend_id = (
            await db.execute(select(Friend.id).where(Friend.vrchat_user_id == "usr_modal"))
        ).scalar_one()

    response = await client.get(f"/friends/{friend_id}/modal")

    assert response.status_code == 200
    assert "モーダル太郎" in response.text
    assert "<nav" not in response.text
    assert "<!DOCTYPE" not in response.text


async def test_friend_detail_modal_not_found(fastapi_app: FastAPI, client: AsyncClient) -> None:
    _login(fastapi_app)

    response = await client.get("/friends/999999/modal")

    assert response.status_code == 404
    assert "見つかりません" in response.text
