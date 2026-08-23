"""デバイスペアリングAPI（デスクトップエージェント⇔ダッシュボード）の統合テスト。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.deps import get_current_user
from app.models.dashboard_user import DashboardUser
from app.services import device_auth_service


@pytest.fixture(autouse=True)
def _isolate_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device_auth_service, "_entries", {})


def _override_current_user(fastapi_app: FastAPI, *, is_admin: bool) -> None:
    async def fake_current_user() -> DashboardUser:
        return DashboardUser(
            id=1,
            discord_user_id="123456789012345678",
            discord_username="tester",
            is_admin=is_admin,
            first_login_at=datetime.now(UTC),
            last_login_at=datetime.now(UTC),
        )

    fastapi_app.dependency_overrides[get_current_user] = fake_current_user


async def test_full_pairing_flow(fastapi_app: FastAPI, client: AsyncClient) -> None:
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

    # 3. 管理者がブラウザで承認する。
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


async def test_approve_forbidden_for_non_admin(fastapi_app: FastAPI, client: AsyncClient) -> None:
    pair_response = await client.post("/api/game-log/agent/pair")
    user_code = pair_response.json()["user_code"]

    _override_current_user(fastapi_app, is_admin=False)
    response = await client.post(
        "/game-log/device/approve", data={"user_code": user_code, "label": ""}
    )
    assert response.status_code == 403


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
