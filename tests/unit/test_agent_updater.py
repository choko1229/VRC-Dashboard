"""デスクトップエージェントのバージョン比較ロジックのユニットテスト。"""

from __future__ import annotations

from desktop_agent.updater import is_newer, parse_version


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
