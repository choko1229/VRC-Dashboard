"""VRChatクライアントのURLエンコーディングのユニットテスト。"""

from __future__ import annotations

from app.services.vrchat.client import _encode_instance_location


def test_encode_instance_location_leaves_colon_and_parens_unescaped() -> None:
    """VRChatのGET /instances/{location}は:・~・()を生のまま要求する（%3A等では400になる）。"""
    location = "wrld_f5f8b3dc-6f33-4b34-97f3-83add2fb224d:e211132e54~region(jp)"
    assert _encode_instance_location(location) == location


def test_encode_instance_location_escapes_unsafe_characters() -> None:
    # 通常のlocation文字列には現れないが、スペース等の本当に危険な文字はエンコードされる。
    assert _encode_instance_location("wrld_abc:1 2") == "wrld_abc:1%202"
