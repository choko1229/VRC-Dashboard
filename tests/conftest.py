"""テスト共通フィクスチャ。各テストはインメモリSQLiteで独立したDBを使う。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  Base.metadataへの登録のためimportが必要
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app


@pytest_asyncio.fixture
async def db_session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory

    await engine.dispose()


@pytest_asyncio.fixture
async def fastapi_app(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[FastAPI]:
    """テストで依存関係のオーバーライド（認証済みユーザーの差し替え等）を行うために公開する。"""
    fastapi_app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with db_session_factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    yield fastapi_app


@pytest_asyncio.fixture
async def client(fastapi_app: FastAPI) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
