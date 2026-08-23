"""デバイスペアリング（ブラウザでログイン→承認）フローのユニットテスト。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services import device_auth_service


@pytest.fixture(autouse=True)
def _isolate_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """モジュールグローバルな辞書をテストごとにリセットする。"""
    monkeypatch.setattr(device_auth_service, "_entries", {})


def test_create_device_code_generates_unique_looking_codes() -> None:
    first = device_auth_service.create_device_code()
    second = device_auth_service.create_device_code()
    assert first.device_code != second.device_code
    assert first.user_code != second.user_code
    assert first.status == "pending"


def test_find_by_user_code_is_case_insensitive_and_trims_whitespace() -> None:
    entry = device_auth_service.create_device_code()
    found = device_auth_service.find_by_user_code(f"  {entry.user_code.lower()}  ")
    assert found is not None
    assert found.device_code == entry.device_code


def test_poll_unknown_device_code_returns_none() -> None:
    assert device_auth_service.poll("does-not-exist") is None


async def test_approve_issues_a_token_and_poll_reflects_it(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    entry = device_auth_service.create_device_code()
    async with db_session_factory() as db:
        approved = await device_auth_service.approve(db, entry.user_code, label="自宅PC")
    assert approved is True

    polled = device_auth_service.poll(entry.device_code)
    assert polled is not None
    assert polled.status == "approved"
    assert polled.issued_token is not None


async def test_approve_unknown_code_returns_false(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        assert await device_auth_service.approve(db, "ZZZZ-ZZZZ") is False


def test_deny_marks_entry_denied() -> None:
    entry = device_auth_service.create_device_code()
    assert device_auth_service.deny(entry.user_code) is True

    polled = device_auth_service.poll(entry.device_code)
    assert polled is not None
    assert polled.status == "denied"

    # 拒否済みのコードはfind_by_user_code（承認/拒否の対象探索）には出てこない。
    assert device_auth_service.find_by_user_code(entry.user_code) is None
