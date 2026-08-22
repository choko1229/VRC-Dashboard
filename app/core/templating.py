"""アプリ全体で共有するJinja2Templatesインスタンス。"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.models.dashboard_user import DashboardUser

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def current_dashboard_user(request: Request) -> DashboardUser | None:
    """テンプレートから安全にログイン中ユーザーを参照するためのヘルパー。

    `get_current_user`依存関係を経由していないリクエスト（未ログインページ等）では
    `request.state.dashboard_user`が存在しないため、その場合はNoneを返す。
    """
    user = getattr(request.state, "dashboard_user", None)
    return user if isinstance(user, DashboardUser) else None


templates.env.globals["current_dashboard_user"] = current_dashboard_user
