"""SQLAlchemy async engine/session基盤。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全モデル共通の宣言的ベースクラス。"""


def create_engine_and_sessionmaker(
    database_url: str, *, echo: bool = False
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url, echo=echo)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory
