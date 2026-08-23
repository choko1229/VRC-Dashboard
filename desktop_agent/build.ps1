# VRCダッシュボード連携ツールをPyInstallerで単一exeにビルドする。
# 使い方（リポジトリ直下から）:
#   .venv/Scripts/pip install -r desktop_agent/requirements-build.txt
#   powershell -File desktop_agent/build.ps1
#
# 生成物: desktop_agent/dist/VRCDashboardAgent.exe
# 新しいバージョンを配布する場合は、先にdesktop_agent/version.pyの__version__を上げてから
# 実行し、生成されたexeを/game-logの「エージェント連携の設定」からアップロードすること。

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

Write-Host "Built: desktop_agent/dist/VRCDashboardAgent.exe"
