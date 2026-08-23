"""テンプレート共通ヘルパー（app.core.templating）のユニットテスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.templating import format_jst


def test_format_jst_converts_aware_utc_to_jst() -> None:
    # UTC 15:00 -> JST 00:00 (翌日)。
    value = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)
    assert format_jst(value, "%Y-%m-%d %H:%M") == "2026-08-24 00:00"


def test_format_jst_treats_naive_datetime_as_utc() -> None:
    # SQLiteから読み出したdatetimeはtzinfo無し(=書き込み時と同じUTC)として扱う。
    naive_value = datetime(2026, 8, 23, 15, 0)
    assert format_jst(naive_value, "%Y-%m-%d %H:%M") == "2026-08-24 00:00"


def test_format_jst_none_returns_placeholder() -> None:
    assert format_jst(None) == "-"
