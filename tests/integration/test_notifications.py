"""通知ページ（VRChat自体の通知ログ）の統合テスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_current_user
from app.models.agent_command import AgentCommand
from app.models.dashboard_user import DashboardUser
from app.models.vrchat_notification import VRChatNotification
from app.services import vrchat_notification_service as svc


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


async def test_notifications_requires_login(client: AsyncClient) -> None:
    response = await client.get("/notifications", follow_redirects=False)
    assert response.status_code == 302


async def test_notifications_page_renders_entries(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _log_in(fastapi_app)
    async with db_session_factory() as db:
        await svc.ingest(
            db,
            pipeline_event="notification",
            content={"id": "not_a", "type": "boop", "senderUsername": "Alice"},
        )

    response = await client.get("/notifications")
    assert response.status_code == 200
    assert "通知" in response.text
    assert "Alice" in response.text


async def test_notifications_content_filters_by_type(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _log_in(fastapi_app)
    async with db_session_factory() as db:
        await svc.ingest(
            db,
            pipeline_event="notification",
            content={"id": "not_boop", "type": "boop", "senderUsername": "Bob"},
        )

    response = await client.get("/notifications/content", params={"notification_type": "invite"})
    assert response.status_code == 200
    assert "通知がありません" in response.text
    assert "Bob" not in response.text


async def test_accept_invite_notification_enqueues_agent_command(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _log_in(fastapi_app)
    async with db_session_factory() as db:
        await svc.ingest(
            db,
            pipeline_event="notification",
            content={
                "id": "not_invite",
                "type": "invite",
                "details": {"worldId": "wrld_x", "instanceId": "1"},
            },
        )
        notification_id = (
            await db.execute(
                select(VRChatNotification.id).where(
                    VRChatNotification.vrchat_notification_id == "not_invite"
                )
            )
        ).scalar_one()

    response = await client.post(f"/notifications/{notification_id}/accept")
    assert response.status_code == 200
    assert "参加" in response.text

    async with db_session_factory() as db:
        command = (await db.execute(select(AgentCommand))).scalars().one()
        assert command.command_type == "join_instance"


async def test_decline_notification_hides_row(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _log_in(fastapi_app)
    async with db_session_factory() as db:
        await svc.ingest(
            db,
            pipeline_event="notification",
            content={"id": "not_msg", "type": "message", "senderUsername": "Carol"},
        )
        notification_id = (
            await db.execute(
                select(VRChatNotification.id).where(
                    VRChatNotification.vrchat_notification_id == "not_msg"
                )
            )
        ).scalar_one()

    response = await client.delete(f"/notifications/{notification_id}")
    assert response.status_code == 200

    async with db_session_factory() as db:
        row = await db.get(VRChatNotification, notification_id)
        assert row is not None
        assert row.is_hidden is True

    list_response = await client.get("/notifications")
    assert "Carol" not in list_response.text
