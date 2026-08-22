"""アプリ全体の設定。

方針: .envは起動前に確定させる必要がある最小限の項目のみとし
（ポート番号等）、Discord OAuthアプリ情報・VRChat API連絡先・VAPID鍵といった
外部連携設定はDB(app_setting)で管理し、WebUI（初期セットアップ画面・設定画面）
から変更できるようにする（app.services.app_config_service参照）。

fernet_master_key/database_url等はデプロイ環境によって上書きしたい場合のための
任意の上級者向けオーバーライドとして残すが、通常は指定不要（デフォルトで動作する）。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 通常はこれだけ指定すればよい ---
    port: int = 8000

    # --- 任意の上級者向けオーバーライド（通常は指定不要） ---
    app_env: str = "development"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./data/vrc_dashboard.db"
    # 未指定の場合はdata/fernet.keyを自動生成して使う（app.core.security参照）。
    fernet_master_key: str = ""

    session_cookie_name: str = "vrc_dashboard_session"
    session_ttl_seconds: int = 60 * 60 * 24 * 30  # 30日

    # Pipeline(WebSocket)再接続ポリシー（ユーザー確認済みのデフォルト値）
    pipeline_reconnect_initial_seconds: float = 5.0
    pipeline_reconnect_max_seconds: float = 60.0
    pipeline_reconnect_notify_after_failures: int = 10


@lru_cache
def get_settings() -> Settings:
    """設定を1度だけ読み込みキャッシュする。"""
    return Settings()
