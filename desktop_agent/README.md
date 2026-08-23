# VRCダッシュボード連携ツール（デスクトップエージェント）

VRChatを起動しているPC上で常駐させる、ダッシュボード本体とは別プロセスのツールです。
タスクトレイに常駐し、VRChatクライアントのローカルログを監視・解析して、訪問した
インスタンスごとの「プレイヤー参加/退出」「動画再生URL」をダッシュボードへ送信します。
ダッシュボードサーバーからの自動更新にも対応しています。

VRChat公式APIには、フレンド以外の参加者の入退室や動画再生URLは一切含まれていません（これらは
VRChatクライアントがローカルに出力するログファイルにのみ存在します）。そのためダッシュボード
本体（Pterodactyl等のリモートサーバー）とは別に、このツールをVRChatを起動している
PC上で動かす必要があります。

## エンドユーザー向け: 使い方

1. ダッシュボードの `/game-log` を管理者アカウントで開き、「エージェント連携の設定」から
   APIキーを発行し、`VRCDashboardAgent.exe` をダウンロードする（まだアップロードされていな
   ければ、下記「開発者向け: ビルド方法」でビルドしてアップロードする）。
2. VRChatを起動しているPCで `VRCDashboardAgent.exe` を実行する。
3. 初回起動時に表示されるダイアログに、ダッシュボードのURLと発行したAPIキーを入力する。
4. タスクトレイにアイコンが常駐する。右クリックメニューから以下ができる。
   - **ダッシュボードを開く**: ブラウザでダッシュボードを開く
   - **今すぐ更新を確認**: サーバーに新しいバージョンが公開されていないか即座に確認する
   - **スタートアップに登録**: Windowsログイン時に自動起動するようにする/解除する
   - **終了**: ツールを終了する

設定（サーバーURL・APIキー）は `%LOCALAPPDATA%\VRCDashboardAgent\config.json` に保存される。

## 自動更新の仕組み

- 起動時と、以後6時間ごとにダッシュボードの `GET /api/game-log/agent/version` を確認する。
- サーバー側のバージョンが手元より新しければ `GET /api/game-log/agent/download` から新しい
  exeをダウンロードし、自分自身のファイルを置き換えて再起動する
  （Windowsでは実行中のexeファイルもリネームできるため、現在のexeを`.old`にリネームしてから
  新しいexeを配置し、新プロセスを起動して自分は終了する）。
- 初回起動時、実行ファイルは書き込み可能な安定パス（`%LOCALAPPDATA%\VRCDashboardAgent\
  VRCDashboardAgent.exe`）へ自動的にコピーされる（自己更新にはこの場所への書き込み権限が要る
  ため）。ダウンロードした場所（Downloadsフォルダ等）からダブルクリックで起動すれば、以後は
  自動的にこの安定パスから動く。

## 開発者向け: ビルド方法

exe化にはPyInstaller・pystray・Pillowを使う（本体アプリの実行には不要なため、
`pyproject.toml`の依存関係には含めていない）。

```bash
.venv/Scripts/pip install -r desktop_agent/requirements-build.txt
powershell -File desktop_agent/build.ps1
```

`desktop_agent/dist/VRCDashboardAgent.exe` が生成される。

### ビルド後の自動アップロード

`build.ps1` はビルドに続けて、`desktop_agent/version.py` の `__version__` と生成したexeを
ダッシュボードへ自動でアップロードする（`POST /game-log/agent/release`）。アップロード先は
次のいずれかで指定する。

- `powershell -File desktop_agent/build.ps1 -ServerUrl https://your-dashboard.example.com -ReleaseToken <トークン>`
- または `desktop_agent/release_config.local.json`（`release_config.local.json.example` を
  コピーして作成。リリーストークンを含むためgit管理対象外）

リリーストークンはダッシュボードの `/game-log` の「エージェント連携の設定」（管理者のみ）
から発行する（ゲームログ取り込み用APIキーとは別物で、新しいビルドをアップロードできる強い
権限を持つため別のシークレットとして扱っている）。

どちらも指定しない場合、またはビルドのみ行いたい場合は `-NoUpload` を付ければアップロードを
スキップしてビルドだけ行う。サーバーは常に最新の1本だけを保持する（バージョン履歴は持たない）。

新しいバージョンを配布する手順:

1. `desktop_agent/version.py` の `__version__` を上げる。
2. `powershell -File desktop_agent/build.ps1` を実行する（ビルド→アップロードが自動で行われる）。

手動でアップロードしたい場合は、ダッシュボードの `/game-log` の「エージェント連携の設定」から
バージョン番号と生成されたexeを直接アップロードすることもできる（管理者としてログインした
セッションでも同じアップロードフォームが使える）。

開発中は `python -m desktop_agent.main` でexe化せずに直接実行できる（この場合、自己更新・
スタートアップ登録は「実行中のファイルを安全に置き換える先」が無いため無効になる）。

## ソースの構成

- `gamelog_parser.py`: VRChatログ1行の解析ロジック（標準ライブラリのみ）
- `gamelog_watcher.py`: ログファイルのtail・イベント送信ロジック（`GameLogWatcher`）。
  単独でPythonスクリプトとして動かすことも可能（`python gamelog_watcher.py --server-url ... --api-key ...`）
- `updater.py`: バージョン比較・ダウンロード・自己置換
- `startup.py`: Windowsスタートアップ（`HKCU\...\Run`）への登録・解除
- `config.py` / `paths.py`: 設定・状態ファイルのパス解決
- `first_run_dialog.py`: 初回起動時の設定入力ダイアログ（tkinter）
- `tray_app.py`: タスクトレイアイコン・メニュー（pystray）
- `main.py`: エントリポイント（開発実行・PyInstallerどちらの起点にもなる）

## 制限・注意事項

- ログ書式は非公式で、VRChatクライアントの更新により変わる可能性があります。うまく取り込まれ
  ない場合は `gamelog_parser.py` の正規表現を実際のログに合わせて調整してください。
- 初めて見るログファイルは過去分を読み込まず、末尾（起動時点）から追跡を始めます。
- サーバーへの送信に失敗した場合は次回送信時にリトライします（最大約5000件までバッファし、
  それを超えると古いイベントから破棄します）。
- exeは自己署名・コード署名を行っていないため、初回実行時にWindows SmartScreenの警告が
  表示される場合があります（「詳細情報」→「実行」で起動できる）。

## TODO

- **コード署名**: 現状exeは無署名のため配布のたびにSmartScreen警告が出る。コード署名
  証明書（EV/OV）を取得し、`build.ps1`のビルド後に`signtool sign`する工程を追加する。
