# VRC事前確認ダッシュボード

VRChatにログインする前に、フレンドのオンライン状況・自分のアバターの準備状況・今日の予定を
一括で確認できる、Discordログイン制のWebダッシュボードです。

FastAPI + Jinja2 + HTMX + SQLite（SQLAlchemy async / Alembic）で構築されています。

## 主な機能

- **Discordログイン**: 許可リスト方式のDiscord OAuth2ログイン。最初にログインしたユーザーは
  自動的に管理者となり、許可リストへ自己登録される（`/setup` 初回セットアップ画面）。
- **フレンド状況**: VRChatの認証情報を保存し、Pipeline（WebSocket）でフレンドのオンライン/
  オフライン・ワールド移動をリアルタイムに反映。
  - 右サイドバーは全フレンド（上限100人、オンライン優先で切り詰め）を常時表示し、
    「同じインスタンス／オンライン／アクティブ／オフライン」に区分（オフラインのみ
    デフォルト折りたたみ）。開閉状態はポーリング更新後も維持され、下部に一覧ページへの
    リンクがある。
  - フレンド一覧ページ（`/friends`）は絞り込みタブなしで、「お気に入り／オンライン／
    オフライン」の3区分を常に一括表示するVRChat公式アプリ風のカード一覧。お気に入り
    （いずれかのグループに所属）は状態を問わず最優先で表示し、オンライン区分の中では
    「同じインスタンス」の枠を上部にまとめる。カードは内容の有無によらず同じ大きさに
    揃えている。カードをクリックするとページ遷移せずモーダルでフレンド詳細を表示する。
  - フレンド詳細（モーダル/フルページ共通）はVRCXのフレンド詳細画面を参考にしたタブ構成
    （情報／グループ／ワールド／アクティビティ／JSON、各タブは開くたびに遅延読み込み）。
    - **情報**: bio・アカウント作成日・会員ランク・自分が付けたノート（VRChatから都度取得、
      未連携/通信失敗時はローカル情報のみで表示継続）、通知ON/OFF、ダッシュボード独自の
      グループ、状態履歴。
    - **グループ**: フレンドが公開しているVRChatグループ一覧（自分と共通のグループには
      バッジ表示）。
    - **ワールド**: フレンドが公開しているワールド一覧。
    - **アクティビティ**: 本アプリが観測したオンライン化イベントからの曜日×時間帯
      ヒートマップ（JST基準）と、最も活発な曜日・ピーク時間帯。
    - **JSON**: 保存済み情報とVRChatから取得したフルプロフィールの生データ。
    - 「共通のフレンド」「お気に入りワールド」「アバター」はVRChat APIで他ユーザーの
      当該データを取得する手段が無い（またはプライバシー上非公開）ため非対応。
- **ゲームログ**（`/game-log`）: VRChatを起動しているPC上で動く別プロセスの
  「VRCダッシュボード連携ツール」（`desktop_agent/`、タスクトレイ常駐・自動更新対応の
  Windows exe）がVRChatクライアントのログファイルを解析し、訪問したインスタンスごとに
  「プレイヤー参加/退出」「動画再生URL」を記録・表示するVRCXのゲームログ画面に近い機能。
  VRChat公式APIにはフレンド以外の参加者の入退室や動画再生URLは一切存在しない（ゲーム
  クライアントのローカルログにのみ出力される）ため、Pipeline/APIとは別経路で成立している。
  エージェントは`/game-log`の「エージェント連携の設定」（管理者のみ）で発行したAPIキーで
  `POST /api/game-log/events`に認証し、`GET /api/game-log/agent/version`で自身の新しい
  ビルドが公開されていないか定期確認して自己更新する。管理者は同画面から新しいビルド
  （exe）をアップロードして配布バージョンを更新できる（`POST /game-log/agent/release`は
  管理者セッションに加え、同画面で発行できる別のリリースアップロード用トークンでも認証でき、
  `desktop_agent/build.ps1`はビルド後にこのトークンで自動アップロードする）。
  詳細は`desktop_agent/README.md`参照。
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
desktop_agent/          # 「VRCダッシュボード連携ツール」（本体アプリとは別プロセス/PCで動くWindows exe。
                        #   タスクトレイ常駐・自動更新。ビルドのみpystray/Pillow/PyInstallerが必要）
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
- VRChatはPipeline(WebSocket)接続時にデフォルトのUser-Agent（`websockets`ライブラリの既定値等）
  を`403 Forbidden`で拒否するため、REST APIと同じ設定済みVRChat用User-Agent
  （`/settings/general`で変更可能）をWebSocketハンドシェイクにも明示的に付与している。
- フレンド詳細の会員ランク（Visitor/New User/User/Known User/Trusted User）は、
  VRChatユーザーオブジェクトの`tags`（`system_trust_*`）から推定している。公式に明文化された
  仕様ではなく、コミュニティで広く知られている慣例に基づく実装のため、VRChat側の変更で
  外れる可能性がある。
- フレンド詳細の「グループ」「ワールド」タブは`GET /users/{id}/groups`・
  `GET /users/{id}/worlds`（そのユーザーが公開している範囲のみ）を、「アクティビティ」タブは
  `friend_presence_event`（本アプリが実際に観測できた期間のオンライン化イベント）を用いる。
  「共通のフレンド」「お気に入りワールド」「アバター」はVRChat APIが他ユーザーの当該データを
  公開していないため実装していない。
- タイムゾーン変換（アクティビティのJST集計等）にはPython標準の`zoneinfo`を使用しており、
  IANAタイムゾーンDBを持たない環境（Windows開発機やslim系Dockerイメージ等）でも動くよう
  `tzdata`パッケージを依存関係に含めている。
- ゲームログ機能のログ解析正規表現（`desktop_agent/gamelog_parser.py`）は、VRChatクライアントの
  非公式なログ書式についてVRCX等の既存コミュニティツールで広く知られているパターンに基づく
  最善努力の実装であり、実際のログでの動作確認・調整が必要になる場合がある。
- 「VRCダッシュボード連携ツール」（`desktop_agent/`）のexeは自己署名・コード署名を行っていない
  ため、初回実行時にWindows SmartScreenの警告が表示される場合がある。自動更新は
  サーバー側の配布バージョンと自身の`desktop_agent/version.py`を比較し、実行中のexeファイルを
  リネームしてから新しいexeに置き換える方式（Windows特有の挙動を利用）で実現している。
  ビルドにのみpystray/Pillow/PyInstallerを使うため、これらは本体アプリの`pyproject.toml`の
  依存関係には含めていない（`desktop_agent/requirements-build.txt`参照）。
