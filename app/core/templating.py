"""アプリ全体で共有するJinja2Templatesインスタンス。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.models.dashboard_user import DashboardUser
from app.schemas.vrchat import (
    parse_instance_privacy_label,
    parse_instance_region_flag,
    parse_platform_label,
)
from app.services.game_log_service import format_duration_seconds
from app.services.vrchat_notification_service import get_type_action, get_type_label

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_JST = ZoneInfo("Asia/Tokyo")


def format_jst(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """DB保存済みのdatetime（UTC、SQLiteからの読み出し時はtzinfo無し）をJSTに変換して表示する。

    テンプレート側で`.strftime()`を直に呼ぶとUTCのまま表示されてしまう
    （本アプリの利用者は日本時間を想定しているため要変換）。Noneの場合は"-"を返す。
    """
    if value is None:
        return "-"
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(_JST).strftime(fmt)


def current_dashboard_user(request: Request) -> DashboardUser | None:
    """テンプレートから安全にログイン中ユーザーを参照するためのヘルパー。

    `get_current_user`依存関係を経由していないリクエスト（未ログインページ等）では
    `request.state.dashboard_user`が存在しないため、その場合はNoneを返す。
    """
    user = getattr(request.state, "dashboard_user", None)
    return user if isinstance(user, DashboardUser) else None


def status_dot_class(activity_status: str) -> str:
    """"join me"/"ask me"等スペースを含む気分ステータス値をCSSクラス名に変換する。"""
    return activity_status.replace(" ", "")


templates.env.globals["current_dashboard_user"] = current_dashboard_user
templates.env.globals["instance_privacy_label"] = parse_instance_privacy_label
templates.env.globals["instance_region_flag"] = parse_instance_region_flag
templates.env.globals["status_dot_class"] = status_dot_class
templates.env.globals["platform_label"] = parse_platform_label
templates.env.globals["notification_type_label"] = get_type_label
templates.env.globals["notification_type_action"] = get_type_action
templates.env.globals["format_duration_seconds"] = format_duration_seconds
templates.env.filters["jst"] = format_jst
