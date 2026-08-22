"""月間/週間カレンダー表示用のグリッド計算（純粋関数、FastAPI非依存）。

週の始まりは日曜日とする（日本語UIでの一般的な慣習に合わせる）。
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

_SUNDAY_START = 6  # Python calendarモジュールでは日曜日=6


def month_grid(year: int, month: int) -> list[list[date]]:
    """指定した年月の週ごとの日付リスト（前後月の日付を含む）を返す。"""
    cal = calendar.Calendar(firstweekday=_SUNDAY_START)
    return list(cal.monthdatescalendar(year, month))


def week_days(start_date: date) -> list[date]:
    """start_dateを含む週（日曜始まり）の7日間を返す。"""
    days_since_sunday = (start_date.weekday() + 1) % 7
    week_start = start_date - timedelta(days=days_since_sunday)
    return [week_start + timedelta(days=i) for i in range(7)]


def previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1
