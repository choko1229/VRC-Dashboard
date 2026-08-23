"""デスクトップエージェントのペアリングURL正規化のユニットテスト。"""

from __future__ import annotations

from desktop_agent.device_pairing import normalize_server_url


def test_normalize_adds_https_scheme_when_missing() -> None:
    assert normalize_server_url("vrc.example.com") == "https://vrc.example.com"


def test_normalize_keeps_explicit_http_scheme() -> None:
    assert normalize_server_url("http://localhost:8000") == "http://localhost:8000"


def test_normalize_strips_trailing_slash() -> None:
    assert normalize_server_url("https://vrc.example.com/") == "https://vrc.example.com"


def test_normalize_strips_surrounding_whitespace() -> None:
    assert normalize_server_url("  vrc.example.com  ") == "https://vrc.example.com"
