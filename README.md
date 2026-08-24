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
    グループの後に見出し無しで続けて表示する（このとき、インスタンスが判明している
    1人だけのフレンドを先に、現在地が本当に不明なフレンドを後にする）。開閉状態は
    ポーリング更新後も維持され、下部に一覧ページへのリンクがある。
  - フレンド一覧ページ（`/friends`）は絞り込みタブなしで、「お気に入り／オンライン／
    オフライン」の3区分を常に一括表示するVRChat公式アプリ風のカード一覧。お気に入り
    （いずれかのグループに所属）は状態を問わず最優先で表示する。オンライン区分は
    フレンドを現在のインスタンスごとにグループ化し（各グループに「🇯🇵 ワールド名・
    公開範囲（人数）」の見出し、人数の多いグループ順）、そのインスタンスにいるのが
    1人だけの場合はグループの見出しを作らない。1人だけのインスタンスのフレンドと、
    インスタンスが不明（プライベート等）なフレンドは、グループの後に見出し無しで続けて
    表示する（別区分には分割しないが、前者を先・後者を後にする）。ワールドが判明している
    フレンドのカードは、
    そのワールドのサムネイル画像を背景に表示する（`friend.current_world_thumbnail_url`）。
    サムネイルは主にPipelineのfriend-online/friend-locationイベントのworldオブジェクトから
    取得するが、「VRChatと同期」の手動再同期時にも`GET /worlds/{id}`から補完する
    （`friends_service.bootstrap_friends_from_vrchat`。同一ワールドは`VRChatClient`内で
    キャッシュされ重複リクエストしない）。カードは内容の有無によらず同じ大きさに揃えている。
    カードをクリックするとページ遷移せずモーダルでフレンド詳細を表示する。
  - フレンド一覧には「テーブル表示」（`/friends?view=table`）もある。VRCXのフレンド一覧
    テーブルに近い構成で、表示名／ランク／ステータス／言語／自己紹介リンク／Joinした回数／
    一緒に居た時間／最後に見た日時／最後に活動した時間／参加日時の列を持ち、列見出し
    クリックでソートできる。ランク・言語・自己紹介リンク・参加日時はVRChatのフルプロフィール
    （`GET /users/{id}`）でしか取得できないため、「VRChatと同期」の手動再同期時にフレンド
    全員分をまとめて取得しDBへ保存する（`friends_service.sync_friend_profile_details`。
    フレンド数が多いと同期に数十秒かかる。取得に失敗したフレンドは既存の値を保持してスキップ
    する）。「Joinした回数」「一緒に居た時間」はVRChat APIには存在せず、ゲームログ
    （`game_log_instance`/`game_log_event`、デスクトップエージェントが稼働していた期間のみ）
    から、自分の滞在期間とそのフレンドのplayer_join〜player_leave期間の重なりを計算した
    概算値（`game_log_service.get_friend_co_presence_stats`）。「共通のフレンド」
    「最後のログイン」はVRChat API・ローカルログのどちらからも他ユーザー分を取得する手段が
    無いため（プライバシー制限、かつログには自分の見た範囲の情報しか無い）非対応。
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
- **プレイ記録**（`/stats`）: 自分自身のプレイ傾向を「いつ／どのぐらい／どんなワールドで／
  だれと」の観点でグラフ表示する。データソースはゲームログ（`game_log_instance`/
  `game_log_event`）のみのため、ゲームログ機能同様デスクトップエージェントが稼働していた
  期間しか集計できない。
  - **いつ**: 訪問開始時刻（JST）を曜日×時間帯のヒートマップで表示
    （`friends_service.compute_activity_stats`と同じCSSグリッド方式のヒートマップ、
    `app/services/play_stats_service.py`の`get_weekday_hour_heatmap`）。
  - **どのぐらい**: 直近30日の1日ごとの合計プレイ時間をCSSバーチャートで表示
    （`get_daily_play_minutes`。日をまたぐ滞在は開始日にまとめて計上する簡易な近似）。
  - **どんなワールドで**: 滞在時間の多いワールド順のランキング（`get_top_worlds`）。
  - **だれと**: 一緒に居た時間の多いフレンド順のランキング。フレンド一覧テーブルの
    「一緒に居た時間」と同じ`game_log_service.get_friend_co_presence_stats`を再利用する
    （`get_all_friends_together`）。
  - グラフは全てプレーンCSS（`<div>`の高さ/幅%指定）で実装しており、Chart.js等の
    JSライブラリは使っていない。
- **通知**（`/notifications`）: VRChat自体の通知（招待/招待リクエスト/フレンドリクエスト/
  メッセージ/Boop/投票キック等）とグループイベント・エコノミー通知等を時系列一覧表示する
  VRCXの「Notification Log」タブに近い機能。フィルター（種類別プルダウン）・検索・
  日付列クリックでのソート・無限スクロールに対応する。
  - VRChat公式が仕様公開しているのはPipelineの`notification`イベント7種類
    （invite/requestInvite/inviteResponse/requestInviteResponse/friendRequest/message/
    boop/voteToKick）のみ。それ以外（`notification-v2`のグループイベント・
    `economy-update`・`instance-queue-*`・`group-*`等）は非公式のため、フィールド抽出に
    失敗した/未知の種類は生のtype文字列をそのまま表示するフォールバックを用意している
    （`app/services/vrchat_notification_service.py`の`_TYPE_META`/`_PARSERS`参照）。
  - **招待の承諾**: VRChatへの参加はサーバー単体では実行できない（実際にVRChatクライアントを
    起動するのはユーザーのPC）ため、「参加」ボタンはVRChatを直接呼び出さず`agent_command`
    テーブルにコマンドを積む。デスクトップエージェント（`desktop_agent/command_poller.py`、
    ゲームログ取り込みと同じペアリング済みトークンを使い回す）が5秒間隔でポーリングし、
    `os.startfile("vrchat://launch?id=<location>")`でVRChatを起動してインスタンスに
    参加させる。フレンドリクエストの承諾/拒否やメッセージ・Boopの削除はVRChat REST API
    だけで完結し、PC側の操作は不要。
- **アバター準備状況**（`/avatars`）: 自分のアバター一覧をVRCX風のテーブル表示で管理する。
  名前／タグ（ダッシュボード独自のタグ）／プラットフォーム／可視性／バージョン／
  プラットフォーム別パフォーマンスランク（PC・Android・iOS）／最終更新日時／作成日時の列を持ち、
  列見出しクリックでソート、可視性・プラットフォームでの絞り込み、名前検索、タグでの絞り込みに
  対応する。「過ごした時間」「インポスター」列はVRChat同期・ゲームログのどちらからも取得手段が
  無いため常に「-」表示（非対応）。各行の「…」メニューから、VRChat本体のアバターデータを
  実際に書き換える操作（名前変更・説明変更・公開/非公開切り替え）ができる
  （`VRChatClient.update_avatar`、`PUT /avatars/{avatarId}`）。VRChatと連携していない場合や
  API呼び出しが失敗した場合は、ローカルDBを更新せずエラーを行内に表示する
  （実データとダッシュボードの表示がズレないようにするため）。画像の変更・コンテンツタグ/
  スタイル・作者タグの変更・インポスター作成は、VRChat側のファイルアップロードAPIや
  非公式エンドポイントの仕様が不確実なため未実装。
- **今日の予定**: 手動登録またはVRChatグループカレンダーからの取り込みによるスケジュール管理
  （月間/週間カレンダー表示）。
- **通知**: ブラウザ通知（Web Push、VAPID鍵は自動生成）、および既存Discord BOTへのHTTP通知
  （BOT側の受け口実装は本リポジトリのスコープ外）。ブラウザ通知は`/settings/notifications`で
  ON/OFFを切り替える。通知クリック時は関連するフレンドの詳細ページ（`/friends/{id}`）へ、
  フレンド以外の通知（Pipeline再接続失敗等）はトップページへ遷移する
  （`NotificationPayload.link_path`）。
- **PWA（プログレッシブWebアプリ）**: `manifest.json`によりホーム画面への追加・スタンドアロン
  起動に対応。Service Worker（`/sw.js`、scopeはオリジン全体`/`）がCSS/JS/フォント/アイコンを
  Cache Storageにキャッシュし（Cache First）、オフライン時のページ遷移では
  `app/static/offline.html`にフォールバックする。フレンドのオンライン状況等はリアルタイム性が
  重要なため、HTML/API応答自体は意図的にキャッシュしない（常にネットワークから取得）。
- **レスポンシブデザイン**: 左ナビは1100px未満で幅232px→変化なし、720px未満でアイコンのみの
  幅72px（さらに480px未満で56px）に縮小する。右側の常時フレンド一覧サイドバーは1100px未満で
  非表示になる。フレンド一覧・フィード・通知一覧などのテーブルは横スクロール対応、モーダルは
  720px未満で画面下部からのシート表示に切り替わる。クラス未指定の`<input>`/`<select>`/
  `<textarea>`にも共通のタッチ操作しやすいサイズ（最小高さ44px）を適用している。
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
├── routers/            # auth / dashboard / friends / feed / vrchat_notifications / game_log / play_stats / avatars / schedule / settings / setup / webpush
├── services/           # VRChatクライアント・Pipeline・各種業務ロジック
├── notifications/       # Discord通知・Web Push通知の抽象化
├── templates/           # Jinja2テンプレート
└── static/              # CSS（LINE Seed JPフォントに統一）・JS・フォント・PWA用アイコン/
                        #   manifest.json・オフラインフォールバックページ
alembic/                # マイグレーション
scripts/seed_allowlist.py  # 許可リストへの手動追加（コンソールが使える場合の代替手段）
desktop_agent/          # 「VRCダッシュボード連携ツール」（本体アプリとは別プロセス/PCで動くWindows exe。
                        #   タスクトレイ常駐・自動更新。ビルドのみpystray/Pillow/PyInstallerが必要）
tests/                  # unit / integration
```

## 補足

- フォントは全て「LINE Seed JP」（Th/Rg/Bd/Eb）に統一している。
- SQLiteは`app.db.base.create_engine_and_sessionmaker`の接続時フックで
  `PRAGMA journal_mode=WAL`・`PRAGMA busy_timeout=30000`・`PRAGMA synchronous=NORMAL`を
  設定している。既定のジャーナルモード（DELETE）は書き込み中に読み取りもブロックするため、
  本番でPipelineイベント処理と複数リクエストの同時DBアクセスが重なると
  `sqlite3.OperationalError: database is locked`が頻発する不具合があった
  （WAL化で読み取り/書き込みを並行させ、busy_timeoutでロック解放を待ってからリトライする
  ようにして解消）。
- 日時系のDBカラムは全てUTCで保存する（`datetime.now(UTC)`。SQLiteは読み出し時にtzinfoを
  落とすため、書き込み時と同じUTCとして扱う必要がある——本アプリで繰り返し出てくる注意点）。
  画面表示は日本時間の利用者を想定しているため、テンプレート側で生の`.strftime()`を呼ぶと
  UTCのまま表示されてしまう不具合になる。必ず`app.core.templating`の`jst`フィルタ
  （`{{ value|jst("%Y-%m-%d %H:%M") }}`、Noneは"-"を返す）を経由してJSTに変換すること。
- Pipelineの`friend-active`/`friend-offline`/`friend-location`イベントはdisplayNameを
  含まないことがあり、以前は`display_name = content.get("displayName") or user_id`という
  「表示名が無ければuser_id（`usr_xxxxxxxx`のUUID）を使う」フォールバックが
  `friend.display_name`に永続化されてしまい、フレンド一覧等に表示名の代わりにUUIDが
  表示され続ける不具合があった（本番で発生）。`app.services.vrchat.pipeline`の
  `_extract_display_name`はuser_idへのフォールバックをせず、取得できなかった場合はNoneを
  返して呼び出し側（`friends_service`の各`handle_friend_*`）が既存の表示名を上書きしない
  ようにして解消した。新規フレンドの初見時のみ、`_get_or_create_friend`が暫定的に
  user_idを使う（次にdisplayName付きのイベントが来れば置き換わる）。
  **既にUUIDに書き換わってしまった既存データは、この修正だけでは直らない**
  （次にdisplayName付きのイベントが来るまで残る）ため、「VRChatと同期」を1回実行して
  REST APIから正しい表示名を取得し直すこと（`bootstrap_friends_from_vrchat`が全フレンド分の
  `display_name`をREST側の値で無条件に上書きする）。
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
- HTMXの`hx-vals='js:{...}'`で`event.target.value`等イベントオブジェクトを参照する書き方は、
  `hx-trigger`に`delay:...ms`が付いていると壊れる（リクエスト送信時点で元のイベントが失われ
  `TypeError: Cannot read properties of undefined (reading 'target')`が発生し、リクエスト自体が
  飛ばない）。検索ボックス等、遅延トリガーと組み合わせる入力欄は`event.target.value`に頼らず、
  input/select自体に`name`属性を付けてHTMXの標準的な値収集に任せること
  （`app/templates/avatars/list.html`のアバター名検索欄参照）。
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
