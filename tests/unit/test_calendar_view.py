"""フェーズ4: カレンダーグリッド計算のユニットテスト。"""

from __future__ import annotations

from datetime import date

from app.services import calendar_view


def test_month_grid_covers_whole_month_with_sunday_start() -> None:
    weeks = calendar_view.month_grid(2026, 2)  # 2026年2月1日は日曜日
    all_days = [day for week in weeks for day in week]

    assert all_days[0].weekday() == 6  # 最初のセルは日曜日
    assert date(2026, 2, 1) in all_days
    assert date(2026, 2, 28) in all_days
    # 各週は7日、月をまたぐ場合も欠けなく埋まっている
    assert all(len(week) == 7 for week in weeks)


def test_week_days_starts_on_sunday() -> None:
    # 2026-08-22は土曜日
    days = calendar_view.week_days(date(2026, 8, 22))
    assert len(days) == 7
    assert days[0].weekday() == 6
    assert date(2026, 8, 22) in days


def test_previous_and_next_month_wrap_around_year() -> None:
    assert calendar_view.previous_month(2026, 1) == (2025, 12)
    assert calendar_view.next_month(2026, 12) == (2027, 1)
    assert calendar_view.previous_month(2026, 6) == (2026, 5)
    assert calendar_view.next_month(2026, 6) == (2026, 7)
