"""VRChat非公式APIレスポンスのスキーマ。

非公式APIは予告なく仕様変更されうるため、想定外のフィールドは無視し
（extra="ignore"）、必要な項目が欠けていても壊れないよう寛容に扱う。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VRChatUser(BaseModel):
    """フル/簡易どちらのユーザーオブジェクトにも対応する寛容なスキーマ。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    display_name: str = Field(alias="displayName")
    # active / join me / ask me / busy / offline
    status: str = "offline"
    status_description: str | None = Field(default=None, alias="statusDescription")
    # "offline" | "private" | "traveling" | "wrld_xxx:instanceId..." 等
    location: str | None = None
    current_avatar_thumbnail_image_url: str | None = Field(
        default=None, alias="currentAvatarThumbnailImageUrl"
    )


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


class VRChatAvatar(BaseModel):
    """自分がアップロード済みのアバター。

    performanceRatingは非公式APIのレスポンスに含まれないことがあるため、
    取得できない場合はNoneのまま許容する（ダッシュボード上は「不明」表示）。
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    name: str
    thumbnail_image_url: str | None = Field(default=None, alias="thumbnailImageUrl")
    release_status: str = Field(default="private", alias="releaseStatus")
    performance_rating: str | None = Field(default=None, alias="performanceRating")
    updated_at: datetime | None = Field(default=None, alias="updated_at")


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
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


def parse_world_id_from_location(location: str | None) -> str | None:
    """"wrld_xxx:instanceId~..." 形式のlocationからworld_idを取り出す。

    "offline"/"private"/"traveling"等、ワールドIDを含まない値の場合はNoneを返す。
    """
    if location is None or location in ("offline", "private", "traveling"):
        return None
    world_id, _, _ = location.partition(":")
    return world_id or None
