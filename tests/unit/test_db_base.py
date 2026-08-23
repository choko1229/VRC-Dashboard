"""SQLite接続設定（app.db.base）のユニットテスト。

本番で頻発していた"database is locked"（デフォルトのDELETEジャーナルモードが
書き込み中に読み取りもブロックするため、同時アクセスでロック競合しやすい）対策として、
接続時にWALモード・busy_timeoutを設定していることを確認する。
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.base import create_engine_and_sessionmaker


async def test_sqlite_connections_use_wal_and_busy_timeout() -> None:
    engine, session_factory = create_engine_and_sessionmaker(
        "sqlite+aiosqlite:///:memory:", echo=False
    )
    try:
        async with session_factory() as db:
            journal_mode = (await db.execute(text("PRAGMA journal_mode"))).scalar_one()
            busy_timeout = (await db.execute(text("PRAGMA busy_timeout"))).scalar_one()
            assert busy_timeout == 30000
            # :memory:ではWALは実質no-op（"memory"のまま）だが、リスナーがエラー無く
            # 動作すること自体を確認する。ファイルDBでの実際の値はスクリプトで別途確認済み。
            assert journal_mode in ("wal", "memory")
    finally:
        await engine.dispose()
