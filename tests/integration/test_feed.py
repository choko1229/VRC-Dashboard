"""フィードページの統合テスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_current_user
from app.models.dashboard_user import DashboardUser
from app.models.friend import Friend
from app.models.friend_presence_event import FriendPresenceEvent


def _log_in(fastapi_app: FastAPI) -> None:
    async def fake_current_user() -> DashboardUser:
        return DashboardUser(
            id=1,
            discord_user_id="123456789012345678",
            discord_username="tester",
            is_admin=False,
            first_login_at=datetime.now(UTC),
            last_login_at=datetime.now(UTC),
        )

    fastapi_app.dependency_overrides[get_current_user] = fake_current_user


async def test_feed_requires_login(client: AsyncClient) -> None:
    response = await client.get("/feed", follow_redirects=False)
    assert response.status_code == 302


async def test_feed_page_renders_entries(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _log_in(fastapi_app)
    async with db_session_factory() as db:
        friend = Friend(vrchat_user_id="usr_a", display_name="Alice")
        db.add(friend)
        await db.commit()
        await db.refresh(friend)
        db.add(
            FriendPresenceEvent(
                friend_id=friend.id,
                event_type="location_change",
                world_name="Test World",
                location="wrld_a:1~region(jp)",
                occurred_at=datetime(2026, 8, 23, 0, 0, tzinfo=UTC),
            )
        )
        await db.commit()

    response = await client.get("/feed")
    assert response.status_code == 200
    assert "フィード" in response.text
    assert "Alice" in response.text
    assert "Test World" in response.text


async def test_feed_rows_filters_by_event_type(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _log_in(fastapi_app)
    async with db_session_factory() as db:
        friend = Friend(vrchat_user_id="usr_a", display_name="Alice")
        db.add(friend)
        await db.commit()
        await db.refresh(friend)
        db.add(
            FriendPresenceEvent(
                friend_id=friend.id,
                event_type="offline",
                occurred_at=datetime(2026, 8, 23, 0, 0, tzinfo=UTC),
            )
        )
        await db.commit()

    response = await client.get("/feed/content", params={"event_type": "online"})
    assert response.status_code == 200
    assert "イベントがありません" in response.text
    assert 'class="feed-tab active"' in response.text


async def test_feed_status_change_shows_transition_dots(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _log_in(fastapi_app)
    async with db_session_factory() as db:
        friend = Friend(vrchat_user_id="usr_a", display_name="Alice")
        db.add(friend)
        await db.commit()
        await db.refresh(friend)
        db.add(
            FriendPresenceEvent(
                friend_id=friend.id,
                event_type="status_change",
                previous_status="busy",
                status="active",
                occurred_at=datetime(2026, 8, 23, 0, 0, tzinfo=UTC),
            )
        )
        await db.commit()

    response = await client.get("/feed")
    assert response.status_code == 200
    assert "status-busy" in response.text
    assert "status-active" in response.text
