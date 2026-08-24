"""VRChat非公式APIレスポンスのスキーマ。

非公式APIは予告なく仕様変更されうるため、想定外のフィールドは無視し
（extra="ignore"）、必要な項目が欠けていても壊れないよう寛容に扱う。
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_REGION_FLAGS: dict[str, str] = {
    "jp": "🇯🇵",
    "us": "🇺🇸",
    "use": "🇺🇸",
    "usw": "🇺🇸",
    "eu": "🇪🇺",
}


class VRChatUser(BaseModel):
    """フル/簡易どちらのユーザーオブジェクトにも対応する寛容なスキーマ。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    display_name: str = Field(alias="displayName")
    # active / join me / ask me / busy / offline （気分ステータス）
    status: str = "offline"
    status_description: str | None = Field(default=None, alias="statusDescription")
    # online（ワールドに滞在中） / active（接続中だがワールド不明） / offline （接続状態）
    state: str = "offline"
    # "offline" | "private" | "traveling" | "wrld_xxx:instanceId..." 等
    location: str | None = None
    current_avatar_thumbnail_image_url: str | None = Field(
        default=None, alias="currentAvatarThumbnailImageUrl"
    )

    # --- 以下は`GET /users/{id}`（フルプロフィール）でのみ取得できる項目。
    #     フレンド一覧(/auth/user/friends)の簡易オブジェクトには含まれない。 ---
    bio: str | None = None
    # VRChatはプライバシー上、時刻を含まない日付文字列（例: "2020-01-01"）を返す。
    date_joined: str | None = Field(default=None, alias="dateJoined")
    last_platform: str | None = Field(default=None, alias="last_platform")
    # 会員ランク（Visitor/New User/User/Known User/Trusted User等）はtagsから推定する。
    tags: list[str] = Field(default_factory=list)
    profile_pic_override: str | None = Field(default=None, alias="profilePicOverride")
    user_icon: str | None = Field(default=None, alias="userIcon")
    # 自分がそのユーザーに付けているメモ（認証済みリクエストの場合のみ返る）。
    note: str | None = None
    # プロフィールに設定した外部リンク（Twitter/Discord等）。
    bio_links: list[str] = Field(default_factory=list, alias="bioLinks")


class VRChatFavoriteGroup(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    name: str
    display_name: str | None = Field(default=None, alias="displayName")
    # "friend" 等。フレンドのお気に入りグループのみ利用する。
    type: str


class VRChatFavorite(BaseModel):
    """お気に入り（フレンドグループへの所属）エントリ。

    tagsには "group_0" 等、所属する お気に入りグループ(VRChatFavoriteGroup.name) を
    指す文字列が入る。
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    favorite_id: str = Field(alias="favoriteId")
    tags: list[str] = Field(default_factory=list)


class VRChatAvatarUnityPackage(BaseModel):
    """アバターのプラットフォーム別ビルド情報（Unityパッケージ）。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    # "standalonewindows" / "android" / "ios" 等
    platform: str | None = None
    performance_rating: str | None = Field(default=None, alias="performanceRating")


class VRChatAvatar(BaseModel):
    """自分がアップロード済みのアバター。

    performanceRatingは非公式APIのレスポンスに含まれないことがあるため、
    取得できない場合はNoneのまま許容する（ダッシュボード上は「不明」表示）。
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    name: str
    description: str | None = None
    thumbnail_image_url: str | None = Field(default=None, alias="thumbnailImageUrl")
    release_status: str = Field(default="private", alias="releaseStatus")
    performance_rating: str | None = Field(default=None, alias="performanceRating")
    version: int | None = None
    unity_packages: list[VRChatAvatarUnityPackage] = Field(
        default_factory=list, alias="unityPackages"
    )
    created_at: datetime | None = Field(default=None, alias="created_at")
    updated_at: datetime | None = Field(default=None, alias="updated_at")

    def performance_rating_for(self, platform_prefix: str) -> str | None:
        """指定プラットフォーム（前方一致、例: "android"）のパフォーマンスランクを返す。

        同一プラットフォームに複数のUnityパッケージがある場合は最初に見つかったものを返す。
        """
        for package in self.unity_packages:
            if package.platform and package.platform.lower().startswith(platform_prefix):
                if package.performance_rating:
                    return package.performance_rating
        return None


class VRChatCalendarEvent(BaseModel):
    """VRChatグループのカレンダーイベント。

    非公式APIのため実際のフィールド名は要検証（コミュニティドキュメント
    vrchat.community 準拠で命名しているが、実データでの確認は未実施）。
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    title: str
    description: str | None = None
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    world_id: str | None = Field(default=None, alias="worldId")


class VRChatWorld(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    name: str
    thumbnail_image_url: str | None = Field(default=None, alias="thumbnailImageUrl")


class VRChatNotificationDto(BaseModel):
    """`GET /auth/user/notifications`（v1）の1件。バックフィル取込用。

    detailsは通知種別ごとに形が異なる"OneOf"（VRChat非公式ドキュメントでも未展開）のため、
    dictのまま保持し、呼び出し側（vrchat_notification_service）で種別ごとに寛容にパースする。
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    type: str
    sender_user_id: str | None = Field(default=None, alias="senderUserId")
    sender_username: str | None = Field(default=None, alias="senderUsername")
    message: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
    seen: bool = False
    created_at: datetime = Field(alias="created_at")


class VRChatGroupSummary(BaseModel):
    """`GET /users/{id}/groups` の1件（そのユーザーが公開しているVRChatグループ所属）。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    group_id: str = Field(alias="groupId")
    name: str
    short_code: str | None = Field(default=None, alias="shortCode")
    icon_url: str | None = Field(default=None, alias="iconUrl")
    member_count: int | None = Field(default=None, alias="memberCount")


class VRChatInstance(BaseModel):
    """`GET /instances/{location}` のレスポンス。インスタンスの現在人数取得に使う。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    n_users: int = Field(default=0, alias="n_users")


def parse_world_id_from_location(location: str | None) -> str | None:
    """"wrld_xxx:instanceId~..." 形式のlocationからworld_idを取り出す。

    "offline"/"private"/"traveling"等、ワールドIDを含まない値の場合はNoneを返す。
    """
    if location is None or location in ("offline", "private", "traveling"):
        return None
    world_id, _, _ = location.partition(":")
    return world_id or None


def parse_instance_privacy_label(location: str | None) -> str:
    """locationのインスタンスタグから公開範囲の日本語ラベルを推定する（コミュニティ整備の
    非公式ドキュメントに基づく慣例的な解釈。VRChat側の仕様変更で外れる可能性がある）。"""
    if location is None or location in ("offline", "private", "traveling"):
        return "プライベート"

    _, _, instance_part = location.partition(":")
    if not instance_part:
        return "パブリック"

    if "~group(" in instance_part:
        if "~groupAccessType(public)" in instance_part:
            return "グループパブリック"
        return "グループ"
    if "~hidden(" in instance_part:
        return "フレンド"
    if "~friends(" in instance_part:
        return "フレンド+"
    if "~private(" in instance_part:
        if "~canRequestInvite" in instance_part:
            return "招待+"
        return "招待"
    return "パブリック"


def parse_instance_region_flag(location: str | None) -> str:
    """locationの"~region(xx)"タグからサーバーリージョンの国旗絵文字を推定する。

    タグが無い/未知のリージョンの場合は地球アイコンにフォールバックする。
    """
    if location is None:
        return "🌐"
    match = re.search(r"~region\(([a-zA-Z]+)\)", location)
    if match is None:
        return "🌐"
    return _REGION_FLAGS.get(match.group(1).lower(), "🌐")


# tagsに含まれる"system_trust_*"から会員ランクを判定する（コミュニティ整備の慣例。
# 公式に明文化された仕様ではないため、VRChat側の変更で外れる可能性がある）。
_TRUST_RANK_BY_TAG: list[tuple[str, str]] = [
    ("system_trust_veteran", "Trusted User"),
    ("system_trust_trusted", "Known User"),
    ("system_trust_known", "User"),
    ("system_trust_basic", "New User"),
]


def parse_trust_rank(tags: list[str]) -> str:
    """フレンドの会員ランク（Visitor/New User/User/Known User/Trusted User）を推定する。"""
    for tag, rank in _TRUST_RANK_BY_TAG:
        if tag in tags:
            return rank
    return "Visitor"


# tagsに含まれる"language_*"から話す言語を判定する（コミュニティ整備の慣例。
# 公式に明文化された仕様ではないため、VRChat側の変更で外れる可能性がある）。
_LANGUAGE_LABEL_BY_TAG: dict[str, str] = {
    "language_jpn": "日本語",
    "language_eng": "English",
    "language_kor": "한국어",
    "language_zho": "中文",
    "language_fra": "Français",
    "language_deu": "Deutsch",
    "language_spa": "Español",
    "language_por": "Português",
    "language_rus": "Русский",
    "language_ita": "Italiano",
}


def parse_languages(tags: list[str]) -> list[str]:
    """フレンドが話す言語一覧を推定する（未知のタグは"language_"を除いた生の値を使う）。"""
    languages: list[str] = []
    for tag in tags:
        if not tag.startswith("language_"):
            continue
        languages.append(_LANGUAGE_LABEL_BY_TAG.get(tag, tag.removeprefix("language_")))
    return languages


def resolve_profile_image_url(user: VRChatUser) -> str | None:
    """プロフィール画像として最も適切なURLを選ぶ（未設定時はアバターサムネイルにフォールバック）。"""
    return (
        user.profile_pic_override
        or user.user_icon
        or user.current_avatar_thumbnail_image_url
    )


_PLATFORM_LABELS: dict[str, str] = {
    "standalonewindows": "PC (Windows)",
    "android": "Android (Quest)",
    "ios": "iOS",
}


def parse_platform_label(last_platform: str | None) -> str | None:
    """last_platformの値（例: "standalonewindows"）を人が読みやすい表記に変換する。"""
    if not last_platform:
        return None
    return _PLATFORM_LABELS.get(last_platform.lower(), last_platform)
