"""デスクトップエージェントのバージョン比較・GitHub Releasesレスポンス解析のユニットテスト。"""

from __future__ import annotations

from desktop_agent.updater import extract_version_and_asset_url, is_newer, parse_version


def test_parse_version() -> None:
    assert parse_version("1.2.3") == (1, 2, 3)


def test_parse_version_ignores_non_numeric_suffix() -> None:
    assert parse_version("1.2.3-beta") == (1, 2, 3)


def test_is_newer_true_for_higher_version() -> None:
    assert is_newer("0.2.0", "0.1.0") is True


def test_is_newer_false_for_equal_version() -> None:
    assert is_newer("0.1.0", "0.1.0") is False


def test_is_newer_false_for_lower_version() -> None:
    assert is_newer("0.1.0", "0.2.0") is False


def test_is_newer_handles_different_segment_counts() -> None:
    assert is_newer("0.1.10", "0.1.9") is True


def test_extract_version_and_asset_url_finds_exe_asset() -> None:
    release = {
        "tag_name": "desktop-agent-v0.2.0",
        "assets": [
            {"name": "source.zip", "browser_download_url": "https://example.com/source.zip"},
            {
                "name": "VRCDashboardAgent.exe",
                "browser_download_url": "https://example.com/VRCDashboardAgent.exe",
            },
        ],
    }
    result = extract_version_and_asset_url(release)
    assert result == ("0.2.0", "https://example.com/VRCDashboardAgent.exe")


def test_extract_version_and_asset_url_ignores_unrelated_tag() -> None:
    release = {"tag_name": "v1.0.0", "assets": []}
    assert extract_version_and_asset_url(release) is None


def test_extract_version_and_asset_url_returns_none_without_exe_asset() -> None:
    release = {
        "tag_name": "desktop-agent-v0.2.0",
        "assets": [{"name": "notes.txt", "browser_download_url": "https://example.com/notes.txt"}],
    }
    assert extract_version_and_asset_url(release) is None
