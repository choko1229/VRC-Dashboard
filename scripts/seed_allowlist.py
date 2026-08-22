"""ダッシュボードへのログイン許可リストに初回エントリを追加するCLIスクリプト。

許可リストが空の状態ではWeb UI経由で自分自身を登録できない
（ログインできないと設定画面に入れないため）ので、このスクリプトで
最初の1件をブートストラップする。

使い方:
    python -m scripts.seed_allowlist <discord_user_id> [--label ラベル]
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.db.base import create_engine_and_sessionmaker
from app.models.discord_allowlist_entry import DiscordAllowlistEntry


async def _seed(discord_user_id: str, label: str | None) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_sessionmaker(settings.database_url)

    async with session_factory() as db:
        existing = await db.execute(
            select(DiscordAllowlistEntry).where(
                DiscordAllowlistEntry.discord_user_id == discord_user_id
            )
        )
        if existing.scalar_one_or_none() is not None:
            print(f"discord_user_id={discord_user_id} は既に許可リストに登録されています。")
        else:
            db.add(DiscordAllowlistEntry(discord_user_id=discord_user_id, label=label))
            await db.commit()
            print(f"discord_user_id={discord_user_id} を許可リストに追加しました。")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Discord許可リストへの初回登録")
    parser.add_argument("discord_user_id", help="許可するDiscordユーザーID（スノーフレーク）")
    parser.add_argument("--label", default=None, help="表示用ラベル（任意）")
    args = parser.parse_args()

    asyncio.run(_seed(args.discord_user_id, args.label))


if __name__ == "__main__":
    main()
