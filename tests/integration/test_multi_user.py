"""複数人利用（Discordアカウントごとに自分のVRChatアカウントでログインして使う）の統合テスト。

- VRChat未ログインのユーザーは機能ページからVRChatログイン画面（/settings/vrchat）へ誘導される。
- データはダッシュボードユーザーごとに分離される。
- アプリ全体の設定（/settings/general）は管理者のみ。
"""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.vrchat_session import VRChatSession
from app.services import schedule_service
from tests.fakes import login_as, seed_vrchat_session


async def test_feature_page_redirects_to_vrchat_login_without_vrchat_session(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    login_as(fastapi_app, user_id=1, vrchat_linked=False)

    response = await client.get("/friends", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/settings/vrchat"


async def test_htmx_request_gets_hx_redirect_without_vrchat_session(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    """HTMXの部分更新では302ではなくHX-Redirectでページ全体を遷移させる。"""
    login_as(fastapi_app, user_id=1, vrchat_linked=False)

    response = await client.get("/friends", headers={"HX-Request": "true"}, follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/settings/vrchat"


async def test_feature_page_accessible_after_vrchat_login(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    login_as(fastapi_app, user_id=1, vrchat_linked=False)
    await seed_vrchat_session(db_session_factory, user_id=1)

    response = await client.get("/friends", follow_redirects=False)

    assert response.status_code == 200


async def test_other_users_vrchat_session_does_not_unlock_gate(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """他のダッシュボードユーザーのVRChatログインは自分の利用条件を満たさない。"""
    await seed_vrchat_session(db_session_factory, user_id=1)
    login_as(fastapi_app, user_id=2, vrchat_linked=False)

    response = await client.get("/friends", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/settings/vrchat"


async def test_invalidated_vrchat_session_redirects_to_vrchat_login(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        db.add(
            VRChatSession(
                dashboard_user_id=1,
                vrchat_user_id="usr_self_1",
                vrchat_display_name="VRC1",
                auth_cookie_encrypted="x",
                is_valid=False,
            )
        )
        await db.commit()
    login_as(fastapi_app, user_id=1, vrchat_linked=False)

    response = await client.get("/stats", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/settings/vrchat"


async def test_vrchat_settings_page_accessible_without_vrchat_session(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    """VRChatログイン画面自体はVRChat未ログインでも開ける（リダイレクトループにならない）。"""
    login_as(fastapi_app, user_id=1, vrchat_linked=False)

    response = await client.get("/settings/vrchat", follow_redirects=False)

    assert response.status_code == 200


async def test_vrchat_settings_page_shows_own_connection(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_vrchat_session(db_session_factory, user_id=1, display_name="ユーザー1のVRC名")
    await seed_vrchat_session(db_session_factory, user_id=2, display_name="ユーザー2のVRC名")
    login_as(fastapi_app, user_id=2, vrchat_linked=False)

    response = await client.get("/settings/vrchat")

    assert response.status_code == 200
    assert "ユーザー2のVRC名" in response.text
    assert "ユーザー1のVRC名" not in response.text


async def test_friends_sidebar_shows_placeholder_without_vrchat_session(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    login_as(fastapi_app, user_id=1, vrchat_linked=False)

    response = await client.get(
        "/partials/friends-sidebar", headers={"HX-Request": "true"}, follow_redirects=False
    )

    assert response.status_code == 200
    assert "HX-Redirect" not in response.headers
    assert "VRChatにログインすると" in response.text


async def test_general_settings_forbidden_for_non_admin(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    login_as(fastapi_app, user_id=1, is_admin=False)

    response = await client.get("/settings/general")

    assert response.status_code == 403


async def test_general_settings_accessible_for_admin(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    login_as(fastapi_app, user_id=1, is_admin=True)

    response = await client.get("/settings/general")

    assert response.status_code == 200


async def test_discord_notification_settings_update_forbidden_for_non_admin(
    fastapi_app: FastAPI, client: AsyncClient
) -> None:
    login_as(fastapi_app, user_id=1, is_admin=False)

    response = await client.post(
        "/settings/notifications/discord",
        data={"bot_url": "https://example.invalid/x", "shared_secret": "s"},
    )

    assert response.status_code == 403


async def test_other_users_schedule_event_is_not_found(
    fastapi_app: FastAPI,
    client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        event = await schedule_service.create_event(
            db,
            1,
            title="ユーザー1の予定",
            event_date=date(2026, 9, 1),
            start_time=None,
            world_id=None,
            world_name=None,
            avatar_id=None,
            memo=None,
        )

    login_as(fastapi_app, user_id=1)
    own_response = await client.get(f"/schedule/events/{event.id}/edit")
    assert own_response.status_code == 200
    assert "ユーザー1の予定" in own_response.text

    login_as(fastapi_app, user_id=2)
    other_response = await client.get(f"/schedule/events/{event.id}/edit")
    assert other_response.status_code == 404
    assert "ユーザー1の予定" not in other_response.text
