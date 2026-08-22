# VRC事前確認ダッシュボード

VRChatにログインする前に、フレンドのオンライン状況・自分のアバターの準備状況・今日の予定を
一括で確認できる、Discordログイン制のWebダッシュボードです。

FastAPI + Jinja2 + HTMX + SQLite（SQLAlchemy async / Alembic）で構築されています。

## 主な機能

- **Discordログイン**: 許可リスト方式のDiscord OAuth2ログイン。最初にログインしたユーザーは
  自動的に管理者となり、許可リストへ自己登録される（`/setup` 初回セットアップ画面）。
- **フレンド状況**: VRChatの認証情報を保存し、Pipeline（WebSocket）でフレンドのオンライン/
  オフライン・ワールド移動をリアルタイムに反映。左サイドバー＋右側の常時表示フレンド一覧、
  グループ管理、通知ON/OFF、履歴閲覧に対応。右サイドバーは「同じインスタンス／オンライン／
  アクティブ」に区分し、各区分は折りたたみ可能（開閉状態はポーリング更新後も維持される）。
  「同じインスタンス」ではワールド名・公開範囲・人数（自分の同室フレンド数／インスタンス
  総人数）を表示する。
  フレンド一覧ページ（`/friends`）は「オンライン／お気に入り／アクティブ／オフライン」の
  タブ切替＋名前検索に対応したカード一覧（VRChat公式アプリ風）で、オンラインタブでは同様に
  「同じインスタンス」の枠を上部にまとめて表示する。どのタブでもオフラインのフレンドは
  一覧の最後に並ぶ。
- **アバター準備状況**: 自分のアバター一覧の同期、タグ付け、メモ管理。
- **今日の予定**: 手動登録またはVRChatグループカレンダーからの取り込みによるスケジュール管理
  （月間/週間カレンダー表示）。
- **通知**: ブラウザ通知（Web Push、VAPID鍵は自動生成）、および既存Discord BOTへのHTTP通知
  （BOT側の受け口実装は本リポジトリのスコープ外）。
- **設定の管理方式**: `.env` にはポート番号など最小限の項目のみを置き、Discord OAuthアプリ
  情報・VRChat APIの連絡先・VAPID鍵といった外部連携設定はDB管理とし、Web UI
  （`/setup` および `/settings/general`）から入力・変更する。

## 技術スタック

- FastAPI（async） / Uvicorn
- SQLAlchemy 2.0（async） + Alembic + SQLite（aiosqlite）
- Jinja2 + HTMX（SPAフレームワークなしのサーバーレンダリング）
- Discord OAuth2（ダッシュボードログイン用、既存Discord BOTとは別アプリ）
- VRChat非公式REST API + Pipeline（WebSocket）
- Fernetによるシークレットのアプリケーションレベル暗号化
- pywebpush（Web Push通知）
- pytest / ruff / mypy --strict

## セットアップ（ローカル開発）

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

`.env` を作成する（`.env.example` をコピー）。通常はポート番号以外は指定不要。

```bash
cp .env.example .env
```

DBマイグレーションを適用して起動する。

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

ブラウザで `http://localhost:8000/setup` を開き、Discord Developer Portalで作成した
OAuth2アプリのClient ID/Secretを入力する（画面に表示されるリダイレクトURLをDiscord側の
Redirectsにも登録する）。保存後、最初にログインしたDiscordアカウントが自動的に管理者となる。
他のユーザーを招待する場合は、ログイン後の「管理」画面（`/settings/allowlist`）から追加する。

## テスト・静的解析

```bash
pytest
ruff check .
mypy .
```

コミット前には、この3つに加えてこのREADMEの内容が現状と合っているかも確認すること。

## デプロイ

### Docker

```bash
docker compose up --build
```

`docker-compose.yml` は環境変数 `PORT`（デフォルト8000）でポートを制御する。

### Pterodactyl（汎用Pythonエッグ）

リポジトリ直下の `main.py` がエントリポイント。`python main.py` 実行でAlembicマイグレーション
適用後にUvicornを起動する。ポートは `SERVER_PORT` → `PORT` → アプリ設定の順で解決する。

## ディレクトリ構成（概要）

```
app/
├── main.py            # アプリ本体（create_app, lifespan）
├── core/               # 設定・セキュリティ・ロギング・共通依存関係
├── db/                 # DBセッション・Base
├── models/             # SQLAlchemyモデル（1テーブル1ファイル）
├── schemas/             # pydanticスキーマ
├── routers/            # auth / dashboard / friends / avatars / schedule / settings / setup / webpush
├── services/           # VRChatクライアント・Pipeline・各種業務ロジック
├── notifications/       # Discord通知・Web Push通知の抽象化
├── templates/           # Jinja2テンプレート
└── static/              # CSS（LINE Seed JPフォントに統一）・JS・フォント
alembic/                # マイグレーション
scripts/seed_allowlist.py  # 許可リストへの手動追加（コンソールが使える場合の代替手段）
tests/                  # unit / integration
```

## 補足

- フォントは全て「LINE Seed JP」（Th/Rg/Bd/Eb）に統一している。
- VRChatの認証情報・Discord OAuthシークレット・VAPID秘密鍵はFernetで暗号化してDBに保存する
  （暗号鍵は `FERNET_MASTER_KEY` 未設定時 `data/fernet.key` に自動生成・永続化される）。
- サイドバーの「同じインスタンス」区分は、Pipelineの`user-location`イベント（自分自身の現在地）
  とフレンドの`current_location`を突き合わせて判定し、インスタンス総人数は
  `GET /instances/{location}` から取得する。`friend-active`イベント（ワールド非滞在での接続中
  状態）や`user-location`はコミュニティ整備の非公式ドキュメントに基づく実装であり、実際の
  VRChatアカウントでの動作は開発環境（サンドボックス）のTLS制限により未検証。初回デプロイ後に
  実際の見え方を確認することを推奨する。
