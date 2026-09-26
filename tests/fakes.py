"""テスト用フェイク実装。"""

from __future__ import annotations

from app.notifications.base import NotificationPayload


class FakeNotificationSender:
    def __init__(self) -> None:
        self.sent: list[NotificationPayload] = []

    async def send(self, payload: NotificationPayload) -> None:
        self.sent.append(payload)


# --- 複数人利用（Discordアカウントごとのデータ分離）対応の統合テスト用ヘルパー ---


def make_dashboard_user(*, user_id: int = 1, is_admin: bool = False):
    """DBに行を作らないフェイクのダッシュボードユーザー（SQLiteではFKが強制されないため十分）。"""
    from datetime import UTC, datetime

    from app.models.dashboard_user import DashboardUser

    return DashboardUser(
        id=user_id,
        discord_user_id=f"{100000000000000000 + user_id}",
        discord_username=f"tester{user_id}",
        is_admin=is_admin,
        first_login_at=datetime.now(UTC),
        last_login_at=datetime.now(UTC),
    )


def login_as(
    fastapi_app,
    *,
    user_id: int = 1,
    is_admin: bool = False,
    vrchat_linked: bool = True,
) -> None:
    """get_current_user（と、vrchat_linked=Trueならget_current_vrchat_userも）を差し替える。

    VRChatログイン必須ゲート自体を検証するテストでは、vrchat_linked=Falseにした上で
    seed_vrchat_sessionで実際のVRChatSession行を作ること。
    """
    from app.core.deps import get_current_user, get_current_vrchat_user

    user = make_dashboard_user(user_id=user_id, is_admin=is_admin)

    async def fake_current_user():
        return user

    fastapi_app.dependency_overrides[get_current_user] = fake_current_user
    if vrchat_linked:
        fastapi_app.dependency_overrides[get_current_vrchat_user] = fake_current_user
    else:
        fastapi_app.dependency_overrides.pop(get_current_vrchat_user, None)


async def seed_vrchat_session(
    db_session_factory,
    *,
    user_id: int,
    vrchat_user_id: str | None = None,
    display_name: str | None = None,
) -> None:
    """指定ダッシュボードユーザーに有効なVRChatSession行を作る。"""
    from app.models.vrchat_session import VRChatSession

    async with db_session_factory() as db:
        db.add(
            VRChatSession(
                dashboard_user_id=user_id,
                vrchat_user_id=vrchat_user_id or f"usr_self_{user_id}",
                vrchat_display_name=display_name or f"VRC{user_id}",
                auth_cookie_encrypted="x",
                is_valid=True,
            )
        )
        await db.commit()


async def seed_allowlisted_user(
    db_session_factory, *, user_id: int, is_admin: bool = False
) -> None:
    """許可リストに登録済みのダッシュボードユーザー行を作る（make_dashboard_userと同じDiscord ID）。

    エージェントトークン認証やPipeline一斉起動は、所有者がまだ許可リストに載っていることを
    DB上で確認するため、それらを通るテストではこの行が必要になる。
    """
    from app.models.discord_allowlist_entry import DiscordAllowlistEntry

    user = make_dashboard_user(user_id=user_id, is_admin=is_admin)
    async with db_session_factory() as db:
        db.add(user)
        db.add(DiscordAllowlistEntry(discord_user_id=user.discord_user_id))
        await db.commit()
