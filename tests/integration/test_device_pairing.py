"""デバイスペアリングAPI（デスクトップエージェント⇔ダッシュボード）の統合テスト。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services import device_auth_service, game_log_agent_token_service
from tests.fakes import login_as, seed_allowlisted_user


@pytest.fixture(autouse=True)
def _isolate_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device_auth_service, "_entries", {})


def _override_current_user(fastapi_app: FastAPI, *, is_admin: bool, user_id: int = 1) -> None:
    # ペアリング承認はVRChat未ログインでも行えるため、VRChat連携済みの差し替えはしない。
    login_as(fastapi_app, user_id=user_id, is_admin=is_admin, vrchat_linked=False)


async def test_full_pairing_flow(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_allowlisted_user(db_session_factory, user_id=1)
    # 1. エージェントがコードを要求する（認証不要）。
    pair_response = await client.post("/api/game-log/agent/pair")
    assert pair_response.status_code == 200
    pair_body = pair_response.json()
    assert set(pair_body) == {
        "device_code",
        "user_code",
        "verification_uri",
        "expires_in",
        "interval",
    }
    assert pair_body["user_code"] in pair_body["verification_uri"]

    # 2. エージェントがポーリングする → まだ承認されていない。
    poll_response = await client.post(
        "/api/game-log/agent/pair/poll", json={"device_code": pair_body["device_code"]}
    )
    assert poll_response.status_code == 200
    assert poll_response.json() == {"status": "pending", "token": None}

    # 3. ログイン中のユーザーがブラウザで承認する。
    _override_current_user(fastapi_app, is_admin=True)
    approve_response = await client.post(
        "/game-log/device/approve",
        data={"user_code": pair_body["user_code"], "label": "自宅PC"},
    )
    assert approve_response.status_code == 200
    assert "承認しました" in approve_response.text

    # 4. エージェントが再度ポーリングする → トークンを受け取れる。
    poll_response = await client.post(
        "/api/game-log/agent/pair/poll", json={"device_code": pair_body["device_code"]}
    )
    assert poll_response.status_code == 200
    poll_body = poll_response.json()
    assert poll_body["status"] == "approved"
    assert poll_body["token"]

    # 5. 受け取ったトークンで実際にゲームログを送信できる。
    ingest_response = await client.post(
        "/api/game-log/events",
        json={"events": []},
        headers={"Authorization": f"Bearer {poll_body['token']}"},
    )
    assert ingest_response.status_code == 200


async def test_non_admin_can_approve_and_owns_issued_token(
    fastapi_app: FastAPI, client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """複数人利用: 非管理者も自分のPCを承認でき、発行されたトークンは承認者の所有になる。"""
    pair_body = (await client.post("/api/game-log/agent/pair")).json()

    _override_current_user(fastapi_app, is_admin=False, user_id=2)
    response = await client.post(
        "/game-log/device/approve", data={"user_code": pair_body["user_code"], "label": ""}
    )
    assert response.status_code == 200
    assert "承認しました" in response.text

    poll_body = (
        await client.post(
            "/api/game-log/agent/pair/poll", json={"device_code": pair_body["device_code"]}
        )
    ).json()
    assert poll_body["status"] == "approved"
    async with db_session_factory() as db:
        assert await game_log_agent_token_service.verify_token(db, poll_body["token"]) == 2
        assert len(await game_log_agent_token_service.list_tokens(db, 2)) == 1
        assert await game_log_agent_token_service.list_tokens(db, 1) == []


async def test_approve_unknown_code_reports_not_found(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    _override_current_user(fastapi_app, is_admin=True)
    response = await client.post(
        "/game-log/device/approve", data={"user_code": "ZZZZ-ZZZZ", "label": ""}
    )
    assert response.status_code == 200
    assert "見つからないか" in response.text


async def test_poll_unknown_device_code_reports_expired(client: AsyncClient) -> None:
    response = await client.post(
        "/api/game-log/agent/pair/poll", json={"device_code": "does-not-exist"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "expired_or_unknown", "token": None}


async def test_device_verification_page_requires_login(client: AsyncClient) -> None:
    response = await client.get("/game-log/device", follow_redirects=False)
    assert response.status_code == 302
