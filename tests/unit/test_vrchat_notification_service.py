"""フェーズ17: VRChat自体の通知ログ（招待/フレンドリクエスト/グループイベント等）の
取込・一覧・アクション。
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.agent_command import AgentCommand
from app.models.vrchat_notification import VRChatNotification
from app.services import vrchat_notification_service as svc


async def test_ingest_notification_v1_invite_extracts_location(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        content = {
            "id": "not_1",
            "type": "invite",
            "senderUserId": "usr_a",
            "senderUsername": "Alice",
            "message": "遊びに来てね",
            "details": {"worldId": "wrld_x", "instanceId": "12345~region(jp)"},
            "created_at": "2026-08-23T10:00:00Z",
        }
        await svc.ingest(db, pipeline_event="notification", content=content)

        row = (
            await db.execute(
                select(VRChatNotification).where(
                    VRChatNotification.vrchat_notification_id == "not_1"
                )
            )
        ).scalar_one()
        assert row.notification_type == "invite"
        assert row.sender_display_name == "Alice"
        assert row.location == "wrld_x:12345~region(jp)"
        assert row.message == "遊びに来てね"


async def test_ingest_is_idempotent_on_duplicate_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        content = {"id": "not_dup", "type": "boop", "senderUsername": "Bob"}
        await svc.ingest(db, pipeline_event="notification", content=content)
        await svc.ingest(db, pipeline_event="notification", content=content)

        rows = (
            (
                await db.execute(
                    select(VRChatNotification).where(
                        VRChatNotification.vrchat_notification_id == "not_dup"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


async def test_ingest_unknown_pipeline_event_is_ignored(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await svc.ingest(db, pipeline_event="some-future-event", content={"id": "x"})
        rows = (await db.execute(select(VRChatNotification))).scalars().all()
        assert rows == []


async def test_ingest_economy_update_creates_synthetic_row(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await svc.ingest(
            db,
            pipeline_event="economy-update",
            content={"description": "600 credits have been added to your account."},
        )
        row = (await db.execute(select(VRChatNotification))).scalars().one()
        assert row.notification_type == "economy_update"
        assert row.message == "600 credits have been added to your account."
        assert row.pipeline_event == "economy-update"


async def test_hide_sync_event_marks_existing_row_hidden(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await svc.ingest(
            db, pipeline_event="notification", content={"id": "not_hide", "type": "message"}
        )
        await svc.ingest(
            db, pipeline_event="hide-notification", content={"notificationId": "not_hide"}
        )

        row = (
            await db.execute(
                select(VRChatNotification).where(
                    VRChatNotification.vrchat_notification_id == "not_hide"
                )
            )
        ).scalar_one()
        assert row.is_hidden is True


async def test_get_notifications_filters_by_type_and_excludes_hidden(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await svc.ingest(
            db, pipeline_event="notification", content={"id": "not_a", "type": "invite"}
        )
        await svc.ingest(
            db, pipeline_event="notification", content={"id": "not_b", "type": "boop"}
        )
        await svc.ingest(
            db, pipeline_event="notification", content={"id": "not_c", "type": "invite"}
        )
        row_c = (
            await db.execute(
                select(VRChatNotification).where(
                    VRChatNotification.vrchat_notification_id == "not_c"
                )
            )
        ).scalar_one()
        row_c.is_hidden = True
        await db.commit()

        entries, has_more = await svc.get_notifications(db, notification_type="invite")
        assert has_more is False
        assert [e.vrchat_notification_id for e in entries] == ["not_a"]


async def test_get_notifications_search_matches_sender_and_message(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await svc.ingest(
            db,
            pipeline_event="notification",
            content={"id": "not_x", "type": "boop", "senderUsername": "Carol"},
        )
        await svc.ingest(
            db,
            pipeline_event="notification",
            content={"id": "not_y", "type": "boop", "senderUsername": "Dave"},
        )

        entries, _ = await svc.get_notifications(db, q="carol")
        assert [e.vrchat_notification_id for e in entries] == ["not_x"]


async def test_get_notifications_sort_dir_toggles_order(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await svc.ingest(
            db,
            pipeline_event="notification",
            content={
                "id": "not_old",
                "type": "boop",
                "created_at": "2026-08-20T00:00:00Z",
            },
        )
        await svc.ingest(
            db,
            pipeline_event="notification",
            content={
                "id": "not_new",
                "type": "boop",
                "created_at": "2026-08-23T00:00:00Z",
            },
        )

        desc_entries, _ = await svc.get_notifications(db, sort_dir="desc")
        asc_entries, _ = await svc.get_notifications(db, sort_dir="asc")
        assert [e.vrchat_notification_id for e in desc_entries] == ["not_new", "not_old"]
        assert [e.vrchat_notification_id for e in asc_entries] == ["not_old", "not_new"]


async def test_enqueue_join_command_creates_pending_agent_command(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await svc.enqueue_join_command(db, location="wrld_x:12345")

        command = (await db.execute(select(AgentCommand))).scalars().one()
        assert command.command_type == "join_instance"
        assert command.status == "pending"
        assert json.loads(command.payload_json) == {"location": "wrld_x:12345"}


async def test_accept_join_action_enqueues_command_without_client(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
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
        row = (
            await db.execute(
                select(VRChatNotification).where(
                    VRChatNotification.vrchat_notification_id == "not_invite"
                )
            )
        ).scalar_one()

        await svc.accept(db, None, row)

        command = (await db.execute(select(AgentCommand))).scalars().one()
        assert json.loads(command.payload_json) == {"location": "wrld_x:1"}
        # 参加系アクションは通知自体を隠さない(再送できるように残す)。
        assert row.is_hidden is False


async def test_decline_without_client_still_hides_row(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        await svc.ingest(
            db, pipeline_event="notification", content={"id": "not_decline", "type": "message"}
        )
        row = (
            await db.execute(
                select(VRChatNotification).where(
                    VRChatNotification.vrchat_notification_id == "not_decline"
                )
            )
        ).scalar_one()

        await svc.decline(db, None, row)

        assert row.is_hidden is True
