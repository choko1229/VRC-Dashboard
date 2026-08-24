"""フェーズ7: locationからの公開範囲ラベル推定のユニットテスト。"""

from __future__ import annotations

from app.schemas.vrchat import (
    VRChatAvatar,
    VRChatUser,
    parse_instance_privacy_label,
    parse_platform_label,
    parse_trust_rank,
    resolve_profile_image_url,
)


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


def test_parse_trust_rank_by_tag() -> None:
    assert parse_trust_rank([]) == "Visitor"
    assert parse_trust_rank(["system_trust_basic"]) == "New User"
    assert parse_trust_rank(["system_trust_known"]) == "User"
    assert parse_trust_rank(["system_trust_trusted"]) == "Known User"
    assert parse_trust_rank(["system_trust_veteran"]) == "Trusted User"


def test_resolve_profile_image_url_prefers_override_then_icon_then_avatar() -> None:
    user = VRChatUser.model_validate(
        {
            "id": "usr_1",
            "displayName": "Alice",
            "profilePicOverride": "https://example.com/override.png",
            "userIcon": "https://example.com/icon.png",
            "currentAvatarThumbnailImageUrl": "https://example.com/avatar.png",
        }
    )
    assert resolve_profile_image_url(user) == "https://example.com/override.png"

    user2 = VRChatUser.model_validate(
        {
            "id": "usr_2",
            "displayName": "Bob",
            "userIcon": "https://example.com/icon.png",
            "currentAvatarThumbnailImageUrl": "https://example.com/avatar.png",
        }
    )
    assert resolve_profile_image_url(user2) == "https://example.com/icon.png"

    user3 = VRChatUser.model_validate(
        {
            "id": "usr_3",
            "displayName": "Carol",
            "currentAvatarThumbnailImageUrl": "https://example.com/avatar.png",
        }
    )
    assert resolve_profile_image_url(user3) == "https://example.com/avatar.png"

    user4 = VRChatUser.model_validate({"id": "usr_4", "displayName": "Dave"})
    assert resolve_profile_image_url(user4) is None


def test_parse_platform_label() -> None:
    assert parse_platform_label(None) is None
    assert parse_platform_label("") is None
    assert parse_platform_label("standalonewindows") == "PC (Windows)"
    assert parse_platform_label("android") == "Android (Quest)"
    assert parse_platform_label("unknown_platform") == "unknown_platform"


def test_avatar_performance_rating_for_platform() -> None:
    avatar = VRChatAvatar.model_validate(
        {
            "id": "avtr_1",
            "name": "Test",
            "unityPackages": [
                {"platform": "standalonewindows", "performanceRating": "Good"},
                {"platform": "android", "performanceRating": "Medium"},
            ],
        }
    )
    assert avatar.performance_rating_for("standalonewindows") == "Good"
    assert avatar.performance_rating_for("android") == "Medium"
    assert avatar.performance_rating_for("ios") is None


def test_avatar_performance_rating_for_no_packages() -> None:
    avatar = VRChatAvatar.model_validate({"id": "avtr_2", "name": "Test"})
    assert avatar.performance_rating_for("android") is None
