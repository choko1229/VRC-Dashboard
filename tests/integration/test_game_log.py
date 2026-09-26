"""ゲームログ機能の統合テスト（取り込みAPIの認証、ページ表示、エージェントトークン管理）。

エージェントトークンはペアリングを承認したダッシュボードユーザーに紐づき、取り込み・PC側コマンドの
取得はそのユーザーのデータに限定される（複数人利用）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.agent_command import AgentCommand
from app.models.game_log_event import GameLogEvent
from app.models.game_log_instance import GameLogInstance
from app.services import game_log_agent_token_service
from tests.fakes import login_as, seed_allowlisted_user

_JOIN_EVENT = {
    "event_type": "instance_join",
    "occurred_at": "2026-08-17T00:00:00+00:00",
    "location": "wrld_a:1",
    "world_id": "wrld_a",
    "world_name": "World A",
}


async def test_ingest_rejects_missing_authorization_header(client: AsyncClient) -> None:
    response = await client.post("/api/game-log/events", json={"events": []})
    assert response.status_code == 401


async def test_ingest_rejects_wrong_token(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with db_session_factory() as db:
        await game_log_agent_token_service.create_token(db, 1, label="test")

    response = await client.post(
        "/api/game-log/events",
        json={"events": []},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


async def test_ingest_accepts_events_with_valid_token(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_allowlisted_user(db_session_factory, user_id=1)
    async with db_session_factory() as db:
        raw_token = await game_log_agent_token_service.create_token(db, 1, label="自宅PC")

    response = await client.post(
        "/api/game-log/events",
        json={"events": [_JOIN_EVENT]},
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": 1}

    async with db_session_factory() as db:
        instances = (await db.execute(select(GameLogInstance))).scalars().all()
        assert len(instances) == 1
        assert instances[0].world_name == "World A"
        assert instances[0].dashboard_user_id == 1


async def test_ingest_stores_events_under_token_owner(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_allowlisted_user(db_session_factory, user_id=1)
    await seed_allowlisted_user(db_session_factory, user_id=2)
    """複数人利用: 取り込まれたゲームログはトークンの所有者（ユーザー2）のものになる。"""
    async with db_session_factory() as db:
        await game_log_agent_token_service.create_token(db, 1, label="ユーザー1のPC")
        user2_token = await game_log_agent_token_service.create_token(db, 2, label="ユーザー2のPC")

    response = await client.post(
        "/api/game-log/events",
        json={"events": [_JOIN_EVENT]},
        headers={"Authorization": f"Bearer {user2_token}"},
    )
    assert response.status_code == 200

    async with db_session_factory() as db:
        instances = (await db.execute(select(GameLogInstance))).scalars().all()
        assert [i.dashboard_user_id for i in instances] == [2]


async def test_a_second_token_does_not_invalidate_the_first(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_allowlisted_user(db_session_factory, user_id=1)
    """複数デバイスをペアリングしても、既存デバイスのトークンが無効化されないこと。"""
    async with db_session_factory() as db:
        first_token = await game_log_agent_token_service.create_token(db, 1, label="PC1")
        await game_log_agent_token_service.create_token(db, 1, label="PC2")

    response = await client.post(
        "/api/game-log/events",
        json={"events": []},
        headers={"Authorization": f"Bearer {first_token}"},
    )
    assert response.status_code == 200


async def test_agent_commands_are_scoped_to_token_owner(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await seed_allowlisted_user(db_session_factory, user_id=1)
    await seed_allowlisted_user(db_session_factory, user_id=2)
    """複数人利用: ユーザー2のトークンではユーザー1宛てのPC側コマンドを取得・完了できない。"""
    async with db_session_factory() as db:
        user2_token = await game_log_agent_token_service.create_token(db, 2, label="PC")
        user1_command = AgentCommand(
            dashboard_user_id=1,
            command_type="join_instance",
            payload_json=json.dumps({"location": "wrld_x:1"}),
        )
        user2_command = AgentCommand(
            dashboard_user_id=2,
            command_type="join_instance",
            payload_json=json.dumps({"location": "wrld_y:1"}),
        )
        db.add_all([user1_command, user2_command])
        await db.commit()
        user1_command_id = user1_command.id
        user2_command_id = user2_command.id

    headers = {"Authorization": f"Bearer {user2_token}"}
    list_response = await client.get("/api/agent/commands", headers=headers)
    assert list_response.status_code == 200
    assert [c["id"] for c in list_response.json()] == [user2_command_id]

    ack_response = await client.post(
        f"/api/agent/commands/{user1_command_id}/ack", json={"status": "done"}, headers=headers
    )
    assert ack_response.status_code == 404
    async with db_session_factory() as db:
        row = await db.get(AgentCommand, user1_command_id)
        assert row is not None
        assert row.status == "pending"


async def test_game_log_page_renders_for_logged_in_user(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    login_as(fastapi_app, user_id=1, is_admin=False)

    response = await client.get("/game-log")

    assert response.status_code == 200
    assert "ゲームログ" in response.text
    # 各ユーザーが自分のPCをペアリングするため、非管理者にも設定パネルを表示する。
    assert "エージェント連携の設定" in response.text


async def test_game_log_instance_events_of_other_user_are_not_shown(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """複数人利用: 他ユーザーのインスタンスIDを指定しても、その入退室ログは表示されない。"""
    async with db_session_factory() as db:
        instance = GameLogInstance(
            dashboard_user_id=1,
            location="wrld_a:1",
            world_id="wrld_a",
            world_name="World A",
            joined_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        )
        db.add(instance)
        await db.commit()
        await db.refresh(instance)
        db.add(
            GameLogEvent(
                instance_id=instance.id,
                event_type="player_join",
                occurred_at=datetime(2026, 8, 1, 0, 1, tzinfo=UTC),
                player_name="秘密の参加者",
            )
        )
        await db.commit()
        instance_id = instance.id

    login_as(fastapi_app, user_id=1)
    own_response = await client.get(f"/game-log/{instance_id}/events")
    assert "秘密の参加者" in own_response.text

    login_as(fastapi_app, user_id=2)
    other_response = await client.get(f"/game-log/{instance_id}/events")
    assert "秘密の参加者" not in other_response.text


async def test_revoke_agent_token_not_allowed_for_other_users_token(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """複数人利用: 他ユーザーがペアリングしたデバイスのトークンは無効化できない。"""
    async with db_session_factory() as db:
        raw_token = await game_log_agent_token_service.create_token(db, 1, label="test")
        tokens = await game_log_agent_token_service.list_tokens(db, 1)

    # 管理者であっても他人のトークンは対象外。
    login_as(fastapi_app, user_id=2, is_admin=True)

    await client.delete(f"/game-log/agent-token/{tokens[0].id}")

    async with db_session_factory() as db:
        assert await game_log_agent_token_service.verify_token(db, raw_token) == 1


async def test_revoke_own_agent_token_allowed_for_non_admin(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with db_session_factory() as db:
        raw_token = await game_log_agent_token_service.create_token(db, 1, label="test")
        tokens = await game_log_agent_token_service.list_tokens(db, 1)

    # VRChat未ログインでも自分のトークンは管理できる。
    login_as(fastapi_app, user_id=1, is_admin=False, vrchat_linked=False)

    response = await client.delete(f"/game-log/agent-token/{tokens[0].id}")

    assert response.status_code == 200
    async with db_session_factory() as db:
        assert await game_log_agent_token_service.verify_token(db, raw_token) is None
