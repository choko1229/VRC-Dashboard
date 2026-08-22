"""Pterodactyl等の汎用Pythonエッグ向けのエントリポイント。

このエッグは "python <PY_FILE>" という形でリポジトリ直下のファイルを直接実行する
仕様のため、通常の `uvicorn app.main:app` 起動とは別に、リポジトリ直下にもこの
スクリプトを用意している。DBマイグレーション適用（Dockerfile運用時のCMDと同等の
処理）とASGIサーバー起動の両方をここで行う。

Docker運用時はこのファイルではなくDockerfileのCMDが使われるため、この
ファイルの有無はDocker運用には影響しない。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

import uvicorn

from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def _resolve_port() -> int:
    # Pterodactylはコンテナに割り当てたポートを SERVER_PORT で渡すことが多い。
    # 未設定の場合はこのアプリ独自の PORT 設定（.env）にフォールバックする。
    env_port = os.environ.get("SERVER_PORT") or os.environ.get("PORT")
    if env_port:
        return int(env_port)
    return get_settings().port


def main() -> None:
    settings = get_settings()
    configure_logging(debug=settings.debug)

    logger.info("DBマイグレーションを適用します")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

    port = _resolve_port()
    logger.info("uvicornを起動します (port=%d)", port)
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
