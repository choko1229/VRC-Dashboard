"""サイドバーのフレンド一覧を「オンライン(インスタンス別)/アクティブ/オフライン」に区分する。

オンラインのフレンドは現在のインスタンスごとにグループ化する（インスタンスが判明している
フレンドを人数の多いグループ順で上位に、判明していないフレンドはグループの後に見出し無しで
続ける）。フレンド一覧ページ（`/friends`）と同じロジックを
`app.services.friends_service.group_online_friends_by_instance`で共有する。

表示件数は`_SIDEBAR_FRIEND_LIMIT`（100人）を上限とし、超える場合はオンライン/
アクティブなフレンドが優先的に残るよう並べ替えてから切り詰める。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.friend import Friend
from app.services.friends_service import FriendInstanceGroup, group_online_friends_by_instance

# サイドバーに表示するフレンドの上限（多すぎる場合はオンライン/アクティブを優先する）。
_SIDEBAR_FRIEND_LIMIT = 100


@dataclass
class SidebarFriendGroups:
    instance_groups: list[FriendInstanceGroup] = field(default_factory=list)
    online_other: list[Friend] = field(default_factory=list)
    active: list[Friend] = field(default_factory=list)
    offline: list[Friend] = field(default_factory=list)


async def get_friend_sidebar_groups(db: AsyncSession) -> SidebarFriendGroups:
    # 上限に達する場合でもオンライン/アクティブが優先的に残るよう並べ替えてから切り詰める。
    online_state_priority = case(
        (Friend.online_state == "online", 0),
        (Friend.online_state == "active", 1),
        else_=2,
    )
    result = await db.execute(
        select(Friend)
        .order_by(online_state_priority, Friend.display_name)
        .limit(_SIDEBAR_FRIEND_LIMIT)
    )
    friends = list(result.scalars().all())

    online_friends: list[Friend] = []
    active_friends: list[Friend] = []
    offline_friends: list[Friend] = []

    for friend in friends:
        if friend.online_state == "offline":
            offline_friends.append(friend)
        elif friend.online_state == "active":
            active_friends.append(friend)
        else:
            online_friends.append(friend)

    instance_groups, online_other = group_online_friends_by_instance(online_friends)

    return SidebarFriendGroups(
        instance_groups=instance_groups,
        online_other=online_other,
        active=active_friends,
        offline=offline_friends,
    )
