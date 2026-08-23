"""SQLAlchemy async engine/session基盤。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全モデル共通の宣言的ベースクラス。"""


def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
    """本番で頻発していた"database is locked"対策。

    デフォルトのジャーナルモード（DELETE）は書き込み中に読み取りもブロックするため、
    Pipelineイベント処理・複数リクエストの同時DBアクセスが重なるとロック競合しやすい。
    WALモードに切り替えて読み取り/書き込みを並行させ、busy_timeoutでロック解放を
    数秒待ってからリトライするようにする（即座にOperationalErrorにしない）。
    :memory:（テスト用）ではWALは実質no-opだが、他のPRAGMAは害が無いため常に適用する。
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_engine_and_sessionmaker(
    database_url: str, *, echo: bool = False
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url, echo=echo)
    if database_url.startswith("sqlite"):
        event.listens_for(engine.sync_engine, "connect")(_set_sqlite_pragma)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory
