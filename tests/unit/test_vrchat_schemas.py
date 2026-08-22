"""フェーズ7: locationからの公開範囲ラベル推定のユニットテスト。"""

from __future__ import annotations

from app.schemas.vrchat import parse_instance_privacy_label


def test_parse_instance_privacy_label_none_or_private_sentinel() -> None:
    assert parse_instance_privacy_label(None) == "プライベート"
    assert parse_instance_privacy_label("private") == "プライベート"
    assert parse_instance_privacy_label("offline") == "プライベート"
    assert parse_instance_privacy_label("traveling") == "プライベート"


def test_parse_instance_privacy_label_public_instance() -> None:
    assert parse_instance_privacy_label("wrld_abc:12345") == "パブリック"


def test_parse_instance_privacy_label_friends_plus() -> None:
    assert parse_instance_privacy_label("wrld_abc:12345~friends(usr_x)~region(us)") == "フレンド+"


def test_parse_instance_privacy_label_friends_only() -> None:
    assert parse_instance_privacy_label("wrld_abc:12345~hidden(usr_x)~region(us)") == "フレンド"


def test_parse_instance_privacy_label_invite_only() -> None:
    assert parse_instance_privacy_label("wrld_abc:12345~private(usr_x)~region(us)") == "招待"


def test_parse_instance_privacy_label_invite_plus() -> None:
    label = parse_instance_privacy_label(
        "wrld_abc:12345~private(usr_x)~canRequestInvite~region(us)"
    )
    assert label == "招待+"


def test_parse_instance_privacy_label_group() -> None:
    assert parse_instance_privacy_label("wrld_abc:12345~group(grp_x)~region(us)") == "グループ"
    label = parse_instance_privacy_label(
        "wrld_abc:12345~group(grp_x)~groupAccessType(public)~region(us)"
    )
    assert label == "グループパブリック"
