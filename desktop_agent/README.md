# VRCダッシュボード連携ツール（デスクトップエージェント）

VRChatを起動しているPC上で常駐させる、ダッシュボード本体とは別プロセスのツールです。
タスクトレイに常駐し、VRChatクライアントのローカルログを監視・解析して、訪問した
インスタンスごとの「プレイヤー参加/退出」「動画再生URL」をダッシュボードへ送信します。
GitHub Releasesからの自動更新にも対応しています。

VRChat公式APIには、フレンド以外の参加者の入退室や動画再生URLは一切含まれていません（これらは
VRChatクライアントがローカルに出力するログファイルにのみ存在します）。そのためダッシュボード
本体（Pterodactyl等のリモートサーバー）とは別に、このツールをVRChatを起動している
PC上で動かす必要があります。

## エンドユーザー向け: 使い方

1. [GitHub Releases](https://github.com/choko1229/VRC-Dashboard/releases)から最新の
   `VRCDashboardAgent.exe`（タグ`desktop-agent-v<version>`）をダウンロードする。
2. VRChatを起動しているPCで `VRCDashboardAgent.exe` を実行する。
3. 初回起動時に表示されるダイアログにダッシュボードのURLを入力し、
   「ブラウザでログインして開始」を押す。既定のブラウザでダッシュボードのペアリング承認画面
   （`/game-log/device`）が自動的に開く。
4. ダッシュボードに管理者としてログインし、表示されたコードが一致することを確認して
   「承認する」を押す（初めて使う場合は先にログインを求められる）。APIキーの手動コピー&
   ペーストは不要。
5. エージェント側の待機ダイアログが自動的に閉じ、タスクトレイにアイコンが常駐する。
   右クリックメニューから以下ができる。
   - **ダッシュボードを開く**: ブラウザでダッシュボードを開く
   - **ログインし直す**: 上記3〜4の手順を再度行い、新しいトークンを取得する
     （トークンが無効化された場合や、設定をリセットしたい場合に使う）
   - **今すぐ更新を確認**: GitHub Releasesに新しいバージョンが公開されていないか即座に確認する
   - **スタートアップに登録**: Windowsログイン時に自動起動するようにする/解除する
   - **終了**: ツールを終了する

設定（サーバーURL・発行されたトークン）は `%LOCALAPPDATA%\VRCDashboardAgent\config.json` に
保存される。ダッシュボード側で個々のトークンを無効化したい場合は、`/game-log`の
「エージェント連携の設定」（管理者のみ）の一覧から行う。複数のPCでエージェントを動かしても、
それぞれ別のトークンが発行されるため、片方を無効化しても他方には影響しない。

## ペアリング（ログイン）の仕組み

OAuth 2.0 Device Authorization Grant（RFC 8628）に似た方式。

1. エージェントが`POST /api/game-log/agent/pair`でペアリングコード一式
   （device_code・8桁のuser_code・verification_uri）を取得する。
2. エージェントは既定のブラウザで`verification_uri`（コード入り）を開く。
3. ダッシュボードに管理者としてログイン中のユーザーがコードを確認して承認する
   （`POST /game-log/device/approve`）。承認するとサーバー側で新しいトークンが1件発行される。
4. エージェントは`POST /api/game-log/agent/pair/poll`を数秒おきにポーリングし、
   承認されたらトークンを受け取って`config.json`に保存する。
5. 以降は`Authorization: Bearer <トークン>`で`POST /api/game-log/events`等に認証する。

ペアリングコードは有効期限10分の使い捨てで、サーバーのメモリ上でのみ管理する
（DBには保存しない）。

## 自動更新の仕組み

- 配布はGitHub Releases（タグ`desktop-agent-v<version>`、`.exe`アセット付き）で行う。
  ダッシュボードサーバー自体はexeを保持・配信しない。
- 起動時と、以後6時間ごとに`GET https://api.github.com/repos/choko1229/VRC-Dashboard/releases/latest`
  を確認する（公開リポジトリのため認証不要）。
- 最新タグのバージョンが手元より新しければアセットをダウンロードし、自分自身のファイルを
  置き換えて再起動する（Windowsでは実行中のexeファイルもリネームできるため、現在のexeを
  `.old`にリネームしてから新しいexeを配置し、新プロセスを起動して自分は終了する）。
- 初回起動時、実行ファイルは書き込み可能な安定パス（`%LOCALAPPDATA%\VRCDashboardAgent\
  VRCDashboardAgent.exe`）へ自動的にコピーされる（自己更新にはこの場所への書き込み権限が要る
  ため）。ダウンロードした場所（Downloadsフォルダ等）からダブルクリックで起動すれば、以後は
  自動的にこの安定パスから動く。

## 開発者向け: ビルド方法

exe化にはPyInstaller・pystray・Pillow・truststoreを使う（本体アプリの実行には不要なため、
`pyproject.toml`の依存関係には含めていない）。GitHub Releasesへのアップロードには
[GitHub CLI（`gh`）](https://cli.github.com/)を使う。

```bash
.venv/Scripts/pip install -r desktop_agent/requirements-build.txt
# ghが無ければ: winget install --id GitHub.cli -e --scope user
gh auth login   # 初回のみ（`repo`スコープが必要）
powershell -File desktop_agent/build.ps1
```

`build.ps1`はビルドに続けて、`desktop_agent/version.py`の`__version__`をタグ名
（`desktop-agent-v<version>`）としてGitHub Releasesへ自動作成/更新する。`gh`が無い/未認証の
場合、または`-NoUpload`を付けた場合はビルドのみ行う。

新しいバージョンを配布する手順:

1. `desktop_agent/version.py`の`__version__`を上げる。
2. `powershell -File desktop_agent/build.ps1`を実行する（ビルド→GitHub Releasesへの
   アップロードが自動で行われる）。

開発中は`python -m desktop_agent.main`でexe化せずに直接実行できる（この場合、自己更新・
スタートアップ登録は「実行中のファイルを安全に置き換える先」が無いため無効になる）。

## ソースの構成

- `gamelog_parser.py`: VRChatログ1行の解析ロジック（標準ライブラリのみ）
- `gamelog_watcher.py`: ログファイルのtail・イベント送信ロジック（`GameLogWatcher`）。
  単独でPythonスクリプトとして動かすことも可能
  （`python gamelog_watcher.py --server-url ... --api-key ...`、ただしその場合は
  `/game-log`の「エージェント連携の設定」から手動でトークンを発行する必要がある）
- `device_pairing.py`: ブラウザでログイン→承認、というペアリングフロー（コード取得・
  ブラウザを開く・ポーリング）。POSTがリダイレクトでGETに化けないようにする独自の
  リダイレクトハンドラも含む（http→https強制リダイレクトの環境向け）
- `command_poller.py`: ダッシュボードの`/notifications`ページで「参加」を押した際の
  PC側操作の委譲（`GET /api/agent/commands`を5秒間隔でポーリングし、`join_instance`
  コマンドを受け取ったら`os.startfile("vrchat://launch?id=<location>")`でVRChatを起動して
  インスタンスに参加する）。gamelog_watcherと同じペアリング済みトークンを使い回す
- `branding.py`: Web UIと揃えた配色・アイコン生成（`tray_app.py`・`first_run_dialog.py`が使う）
- `updater.py`: GitHub Releasesでのバージョン比較・ダウンロード・自己置換
- `startup.py`: Windowsスタートアップ（`HKCU\...\Run`）への登録・解除
- `config.py` / `paths.py`: 設定・状態ファイルのパス解決
- `first_run_dialog.py`: 初回起動時の設定入力・ペアリング待ちダイアログ（tkinter）
- `tray_app.py`: タスクトレイアイコン・メニュー（pystray）
- `main.py`: エントリポイント（開発実行・PyInstallerどちらの起点にもなる。OSネイティブの
  TLS証明書検証を使うための`truststore.inject_into_ssl()`もここで最初に呼ぶ）

## 制限・注意事項

- ログ書式は非公式で、VRChatクライアントの更新により変わる可能性があります。うまく取り込まれ
  ない場合は `gamelog_parser.py` の正規表現を実際のログに合わせて調整してください。
- 初めて見るログファイルは過去分を読み込まず、末尾（起動時点）から追跡を始めます。
- サーバーへの送信に失敗した場合は次回送信時にリトライします（最大約5000件までバッファし、
  それを超えると古いイベントから破棄します）。
- exeは自己署名・コード署名を行っていないため、初回実行時にWindows SmartScreenの警告が
  表示される場合があります（「詳細情報」→「実行」で起動できる）。
- PyInstaller同梱のOpenSSLが、環境によっては一部サイトのTLS証明書チェーン検証に失敗する
  ことがあるため（`CERTIFICATE_VERIFY_FAILED: Basic Constraints of CA cert not marked
  critical`）、`truststore`パッケージでOSのネイティブ証明書検証に差し替えている。
- ダッシュボードがCloudflare等のWAF/ボット対策の背後にある場合、Pythonの`urllib`が送る
  既定のUser-Agent（`Python-urllib/x.y`）が403でブロックされることがある。エージェントの
  全リクエストに明示的な`User-Agent: VRCDashboardAgent`を付与して回避している
  （v0.1.2で修正。この問題が再発する場合はダッシュボード側のWAF設定でこのUser-Agentを
  許可するか、ボット対策のセンシティビティを見直すこと）。

- `command_poller.py`の`vrchat://launch?id=...`によるVRChat起動は、VRChatクライアント
  （またはSteam経由のランチャー）がこのURIスキームをOSに登録済みであることに依存する
  （通常はVRChat公式クライアントのインストール時に自動登録される）。実機PCでの起動確認は
  本セッションでは未実施（サーバー側のコマンドキュー投入・エージェントのポーリング/ack
  往復はテスト・実機ブラウザで確認済み）。

## TODO

- **コード署名**: 現状exeは無署名のため配布のたびにSmartScreen警告が出る。コード署名
  証明書（EV/OV）を取得し、`build.ps1`のビルド後に`signtool sign`する工程を追加する。
