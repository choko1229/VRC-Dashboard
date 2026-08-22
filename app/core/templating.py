"""アプリ全体で共有するJinja2Templatesインスタンス。"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.models.dashboard_user import DashboardUser
from app.schemas.vrchat import parse_instance_privacy_label, parse_instance_region_flag

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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
