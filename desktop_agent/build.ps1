# VRCダッシュボード連携ツールをPyInstallerで単一exeにビルドし、GitHub Releasesへ
# アップロードする。
#
# 使い方（リポジトリ直下から）:
#   .venv/Scripts/pip install -r desktop_agent/requirements-build.txt
#   winget install --id GitHub.cli -e   （未インストールの場合。https://cli.github.com/ 参照）
#   gh auth login                        （初回のみ）
#   powershell -File desktop_agent/build.ps1
#
# GitHub CLI(gh)が無い/未認証の場合はビルドのみ行い、アップロードはスキップする。
# -NoUpload を付けてもビルドのみになる。
#
# 生成物: desktop_agent/dist/VRCDashboardAgent.exe
# バージョンはdesktop_agent/version.pyの__version__を単一の情報源とする。
# 新しいバージョンを配布する場合は、先にそちらを上げてからこのスクリプトを実行すること。
# リリースはタグ "desktop-agent-v<version>" として作成する
# （desktop_agent/updater.pyのRELEASE_TAG_PREFIXと対応させること）。

param(
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
$tag = "desktop-agent-v$version"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "GitHub CLI(gh)が見つからないため、アップロードはスキップします。"
    Write-Host "https://cli.github.com/ からインストールし、'gh auth login' を実行してください。"
    exit 0
}

& gh release view $tag *>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "既存のリリース $tag にアセットをアップロードします..."
    & gh release upload $tag $exePath --clobber
} else {
    Write-Host "新しいリリース $tag を作成します..."
    & gh release create $tag $exePath `
        --title "VRCダッシュボード連携ツール v$version" `
        --notes "自動ビルド（desktop_agent/build.ps1）"
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "GitHub Releaseの作成/アップロードに失敗しました（終了コード: $LASTEXITCODE）"
    exit 1
}

Write-Host "GitHub Releases ($tag) へアップロードしました。"
