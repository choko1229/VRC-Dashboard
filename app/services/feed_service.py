"""全フレンド横断のアクティビティフィード（VRCXの「フィード」タブに相当）。

friend_presence_event（フレンド単位の状態変化ログ）を、フレンドをまたいで時系列に
一覧・絞り込みできるようにする。イベント種別ごとに書き込まれる内容は
app.services.friends_service の各handle_friend_*関数を参照。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.friend import Friend
from app.models.friend_group_membership import FriendGroupMembership
from app.models.friend_presence_event import FriendPresenceEvent

_PAGE_SIZE = 50

FeedEventType = Literal[
    "online", "offline", "location_change", "status_change", "avatar_change"
]
_VALID_EVENT_TYPES: frozenset[str] = frozenset(
    ("online", "offline", "location_change", "status_change", "avatar_change")
)


@dataclass
class FeedEntry:
    event: FriendPresenceEvent
    friend: Friend


async def get_feed_entries(
    db: AsyncSession,
    *,
    page: int = 0,
    event_type: str | None = None,
    favorites_only: bool = False,
    search: str = "",
) -> tuple[list[FeedEntry], bool]:
    """フィードの1ページ分を新しい順に取得する。(結果, 次ページの有無) を返す。"""
    query = select(FriendPresenceEvent, Friend).join(
        Friend, FriendPresenceEvent.friend_id == Friend.id
    )

    if event_type and event_type in _VALID_EVENT_TYPES:
        query = query.where(FriendPresenceEvent.event_type == event_type)
    if favorites_only:
        query = query.where(
            Friend.id.in_(select(FriendGroupMembership.friend_id).distinct())
        )
    if search.strip():
        query = query.where(Friend.display_name.ilike(f"%{search.strip()}%"))

    query = (
        query.order_by(FriendPresenceEvent.occurred_at.desc(), FriendPresenceEvent.id.desc())
        .offset(page * _PAGE_SIZE)
        .limit(_PAGE_SIZE + 1)
    )
    rows = (await db.execute(query)).all()
    has_more = len(rows) > _PAGE_SIZE
    rows = rows[:_PAGE_SIZE]
    entries = [FeedEntry(event=event, friend=friend) for event, friend in rows]
    return entries, has_more
