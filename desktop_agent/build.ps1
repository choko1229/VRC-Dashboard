# VRCダッシュボード連携ツールをPyInstallerで単一exeにビルドし、そのままダッシュボードへ
# アップロードする（サーバーURL・リリーストークンが分かる場合）。
#
# 使い方（リポジトリ直下から）:
#   .venv/Scripts/pip install -r desktop_agent/requirements-build.txt
#   powershell -File desktop_agent/build.ps1
#
# アップロード先は次の優先順で解決する:
#   1. -ServerUrl / -ReleaseToken パラメータ
#   2. desktop_agent/release_config.local.json（release_config.local.json.example参照。
#      秘密情報を含むためgit管理対象外）
# どちらも無ければビルドのみ行い、アップロードはスキップする。
# -NoUpload を付けるとビルドのみ行う。
#
# リリーストークンは/game-logの「エージェント連携の設定」（管理者のみ）から発行する
# （ゲームログ取り込み用APIキーとは別物）。
#
# 生成物: desktop_agent/dist/VRCDashboardAgent.exe
# バージョンはdesktop_agent/version.pyの__version__を単一の情報源とする。
# 新しいバージョンを配布する場合は、先にそちらを上げてからこのスクリプトを実行すること。

param(
    [string]$ServerUrl,
    [string]$ReleaseToken,
    [switch]$NoUpload
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

& .venv/Scripts/python -m PyInstaller `
    --onefile `
    --windowed `
    --name VRCDashboardAgent `
    --distpath desktop_agent/dist `
    --workpath desktop_agent/build `
    --specpath desktop_agent `
    --noconfirm `
    desktop_agent/main.py

$exePath = "desktop_agent/dist/VRCDashboardAgent.exe"
Write-Host "Built: $exePath"

if ($NoUpload) {
    Write-Host "-NoUpload指定のため、アップロードはスキップします。"
    exit 0
}

$versionContent = Get-Content desktop_agent/version.py -Raw
if ($versionContent -notmatch '__version__\s*=\s*"([^"]+)"') {
    Write-Warning "desktop_agent/version.pyからバージョンを読み取れませんでした。アップロードをスキップします。"
    exit 0
}
$version = $Matches[1]

$configPath = "desktop_agent/release_config.local.json"
if ((-not $ServerUrl) -or (-not $ReleaseToken)) {
    if (Test-Path $configPath) {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
        if (-not $ServerUrl) { $ServerUrl = $config.server_url }
        if (-not $ReleaseToken) { $ReleaseToken = $config.release_token }
    }
}

if ((-not $ServerUrl) -or (-not $ReleaseToken)) {
    Write-Host "サーバーURL/リリーストークンが未設定のため、自動アップロードはスキップします。"
    Write-Host "-ServerUrl/-ReleaseToken を指定するか、$configPath を作成してください（$configPath.example 参照）。"
    exit 0
}

Write-Host "v$version を $ServerUrl へアップロードします..."
$uploadUrl = "$($ServerUrl.TrimEnd('/'))/game-log/agent/release"
& curl.exe -sS -X POST `
    -H "Authorization: Bearer $ReleaseToken" `
    -F "version=$version" `
    -F "file=@$exePath;filename=VRCDashboardAgent.exe" `
    $uploadUrl
if ($LASTEXITCODE -ne 0) {
    Write-Error "アップロードに失敗しました（curl終了コード: $LASTEXITCODE）"
    exit 1
}
Write-Host ""
Write-Host "v$version をアップロードしました。"
