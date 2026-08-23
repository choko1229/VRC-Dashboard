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
    「オンライン／アクティブ／オフライン」に区分（オフラインのみデフォルト折りたたみ）。
    オンライン区分はフレンド一覧ページと同じロジック
    （`friends_service.group_online_friends_by_instance`）でインスタンスごとに
    グループ化し（2人以上いるインスタンスのみ見出しを作る）、1人だけ/不明なフレンドは
    グループの後に見出し無しで続けて表示する。開閉状態はポーリング更新後も維持され、
    下部に一覧ページへのリンクがある。
  - フレンド一覧ページ（`/friends`）は絞り込みタブなしで、「お気に入り／オンライン／
    オフライン」の3区分を常に一括表示するVRChat公式アプリ風のカード一覧。お気に入り
    （いずれかのグループに所属）は状態を問わず最優先で表示する。オンライン区分は
    フレンドを現在のインスタンスごとにグループ化し（各グループに「🇯🇵 ワールド名・
    公開範囲（人数）」の見出し、人数の多いグループ順）、そのインスタンスにいるのが
    1人だけの場合はグループの見出しを作らない。インスタンスが不明（プライベート等）な
    フレンドと、1人だけのインスタンスのフレンドは、グループの後に見出し無しで続けて
    表示する（別区分には分割しない）。ワールドが判明しているフレンドのカードは、
    そのワールドのサムネイル画像を背景に表示する（`friend.current_world_thumbnail_url`）。
    サムネイルは主にPipelineのfriend-online/friend-locationイベントのworldオブジェクトから
    取得するが、「VRChatと同期」の手動再同期時にも`GET /worlds/{id}`から補完する
    （`friends_service.bootstrap_friends_from_vrchat`。同一ワールドは`VRChatClient`内で
    キャッシュされ重複リクエストしない）。カードは内容の有無によらず同じ大きさに揃えている。
    カードをクリックするとページ遷移せずモーダルでフレンド詳細を表示する。
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
- **フィード**（`/feed`）: 全フレンド横断の活動履歴を時系列一覧表示するVRCXの「フィード」
  タブに近い機能。「現在地／オンライン／オフライン／ステータス／アバター」の種別タブ、
  お気に入りのみ表示、フレンド名検索に対応する。各行は日付・種別・ユーザー・詳細を
  1行に収めるコンパクト表示（省略はellipsisで、はみ出しはツールチップではなく詰め）。
  下端までスクロールすると`hx-trigger="revealed"`により次の50件を自動読み込みする
  （ボタン操作不要の無限スクロール）。
  ステータス変化は変化前後を色付きドットの遷移で表示し、アバター変更は`friend-update`
  イベントでの`currentAvatarThumbnailImageUrl`の差分検知により記録する
  （`friend_presence_event.event_type`に`status_change`/`avatar_change`を追加）。
  「自己紹介」の変更検知はVRChat APIから継続的に低コストで取得する手段が無いため非対応。
- **ゲームログ**（`/game-log`）: VRChatを起動しているPC上で動く別プロセスの
  「VRCダッシュボード連携ツール」（`desktop_agent/`、タスクトレイ常駐・自動更新対応の
  Windows exe）がVRChatクライアントのログファイルを解析し、訪問したインスタンスごとに
  「プレイヤー参加/退出」「動画再生URL」を記録・表示するVRCXのゲームログ画面に近い機能。
  VRChat公式APIにはフレンド以外の参加者の入退室や動画再生URLは一切存在しない（ゲーム
  クライアントのローカルログにのみ出力される）ため、Pipeline/APIとは別経路で成立している。
  - **配布**: [GitHub Releases](https://github.com/choko1229/VRC-Dashboard/releases)
    （タグ`desktop-agent-v<version>`）でexeを配布する。ダッシュボードサーバー自体はexeを
    保持・配信しない。`desktop_agent/build.ps1`がビルド後にGitHub CLI（`gh`）で
    自動的にリリースを作成/更新する。
  - **認証**: APIキーの手動コピー&ペーストではなく、OAuth 2.0 Device Authorization Grant
    （RFC 8628）に似た「ブラウザでログイン→承認」方式でペアリングする。エージェント起動時に
    `POST /api/game-log/agent/pair`でコードを取得してブラウザで`/game-log/device`を開き、
    管理者としてログイン中のユーザーが表示されたコードを承認すると、エージェントが
    `POST /api/game-log/agent/pair/poll`のポーリングでトークンを自動的に受け取る
    （`game_log_agent_token`テーブルで複数デバイス分のトークンを個別に管理するため、
    後から別のPCをペアリングしても既存デバイスのトークンは無効化されない）。
  - **自動更新**: 起動時と6時間ごとにGitHub Releasesの最新版を確認し、自身より新しければ
    ダウンロードして自己置換・再起動する（サーバーには自動更新用のエンドポイントを持たない）。
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
├── routers/            # auth / dashboard / friends / feed / game_log / avatars / schedule / settings / setup / webpush
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
- フレンド一覧／サイドバーの「オンライン」区分は、各フレンドの`current_location`を突き合わせて
  インスタンスごとにグループ化する（`friends_service.group_online_friends_by_instance`。人数の
  多いグループ順、判明していないフレンドは見出し無しで末尾）。VRChat側のインスタンス総人数
  （`GET /instances/{location}`、`VRChatClient.get_instance`）は多数の異なるインスタンスに対して
  都度APIを叩くことになりレート制限のリスクがあるため、あえて取得・表示していない。
  本番環境での実動作確認により、`GET /instances/{location}`のlocationは`:`・`~`・`()`を
  percent-encodeすると400 Bad Requestになる（生のまま渡す必要がある）ことが判明し修正済み
  （`app/services/vrchat/client.py`の`_encode_instance_location`参照）。
- `vrchat_session.self_location`はPipelineの`user-location`イベント（自分自身の現在地）で
  更新され続けているが、現状どの画面からも参照していない（フレンドのグループ化は各フレンド
  自身の`current_location`のみで完結するため）。`friend-active`イベント（ワールド非滞在での
  接続中状態）や`user-location`はコミュニティ整備の非公式ドキュメントに基づく実装。
  - `user-location`イベントは実際にワールドを移動した瞬間にしか送られないため、Pipeline接続
    時点で既にどこかのワールドに滞在している場合は次に移動するまで`self_location`が`None`の
    ままになる。接続確立時に`GET /auth/user`から現在地を取得して補完している
    （`app/services/vrchat/pipeline.py`の`_default_seed_self_location`参照。テストでは
    実ネットワーク呼び出しを避けるため`PipelineManager`の`seed_self_location`引数で
    差し替え可能にしている）。
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
  GitHub Releasesの最新タグと自身の`desktop_agent/version.py`を比較し、実行中のexeファイルを
  リネームしてから新しいexeに置き換える方式（Windows特有の挙動を利用）で実現している。
  ビルドにのみpystray/Pillow/PyInstaller/truststoreを使うため、これらは本体アプリの
  `pyproject.toml`の依存関係には含めていない（`desktop_agent/requirements-build.txt`参照）。
- デスクトップエージェントの同梱Python（PyInstallerがexeに含めるOpenSSL）は、環境によっては
  GitHub等一部サイトのTLS証明書チェーン検証に失敗することがある
  （`CERTIFICATE_VERIFY_FAILED: Basic Constraints of CA cert not marked critical`）。
  これはOpenSSL 3.x系の厳格な検証とサイト側の証明書チェーンの組み合わせによる既知の相性問題で、
  Windows標準のTLS検証（curl等が使うもの）では発生しない。`truststore`パッケージでOSの
  ネイティブ証明書検証に差し替えることで回避している（`desktop_agent/main.py`参照）。
- フィードのステータス/アバター変更検知（`friends_service.handle_friend_status_update`）は、
  フレンドを初めて観測した際（`current_avatar_thumbnail_url`が未取得からの初回取得）は
  「変更」とみなさない（Noneから実URLへの遷移は毎回の初回同期で必ず起きるため、
  記録すると全フレンドについて意味の無い「アバター変更」イベントが大量発生してしまう）。
  ステータスの変化前後（例: 取り込み中/退席中→オンライン）は`previous_status`列に保存し、
  フィード側で色付きドット→色付きドットの遷移として表示する。
