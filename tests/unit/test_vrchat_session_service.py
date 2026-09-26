"""VRChatログインセッション（ユーザーごとの分離）のユニットテスト。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import SecretCipher
from app.services import vrchat_session_service
from tests.fakes import seed_allowlisted_user

_TEST_FERNET_KEY = "gdsF_NX-iLtl8QLOwmQyFeEdQtOmWXiAlHD4kTrLuh4="


async def _save(db: AsyncSession, cipher: SecretCipher, user_id: int, vrchat_user_id: str) -> None:
    await vrchat_session_service.save_session(
        db,
        cipher,
        user_id,
        vrchat_user_id=vrchat_user_id,
        vrchat_display_name=vrchat_user_id,
        auth_cookie=f"auth_{vrchat_user_id}",
        two_factor_cookie=None,
    )


async def test_save_session_does_not_invalidate_other_users_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    await seed_allowlisted_user(db_session_factory, user_id=1)
    await seed_allowlisted_user(db_session_factory, user_id=2)
    async with db_session_factory() as db:
        await _save(db, cipher, 2, "usr_two")
        await _save(db, cipher, 1, "usr_one_old")
        # ユーザー1の再ログインは、ユーザー1の旧セッションだけを無効化する。
        await _save(db, cipher, 1, "usr_one_new")

        session_u1 = await vrchat_session_service.get_active_session(db, 1)
        session_u2 = await vrchat_session_service.get_active_session(db, 2)
        assert session_u1 is not None
        assert session_u1.vrchat_user_id == "usr_one_new"
        assert session_u2 is not None
        assert session_u2.vrchat_user_id == "usr_two"

        assert await vrchat_session_service.get_decrypted_cookies(db, cipher, 2) == (
            "auth_usr_two",
            None,
        )
        assert sorted(await vrchat_session_service.list_user_ids_with_active_session(db)) == [
            1,
            2,
        ]

        await vrchat_session_service.mark_invalid(db, 1)
        assert await vrchat_session_service.get_active_session(db, 1) is None
        assert await vrchat_session_service.get_active_session(db, 2) is not None


async def test_find_other_user_with_vrchat_account(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cipher = SecretCipher(_TEST_FERNET_KEY)
    async with db_session_factory() as db:
        await _save(db, cipher, 1, "usr_shared")

        # 別ユーザーが同じVRChatアカウントでログインしようとした場合は検出する。
        assert (
            await vrchat_session_service.find_other_user_with_vrchat_account(db, 2, "usr_shared")
            == 1
        )
        # 本人の再ログインや、別のVRChatアカウントは対象外。
        assert (
            await vrchat_session_service.find_other_user_with_vrchat_account(db, 1, "usr_shared")
            is None
        )
        assert (
            await vrchat_session_service.find_other_user_with_vrchat_account(db, 2, "usr_other")
            is None
        )

        # 無効化済みのセッションは対象外。
        await vrchat_session_service.mark_invalid(db, 1)
        assert (
            await vrchat_session_service.find_other_user_with_vrchat_account(db, 2, "usr_shared")
            is None
        )
