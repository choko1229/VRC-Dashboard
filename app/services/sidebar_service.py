"""サイドバーのフレンド一覧を「同じインスタンス/オンライン/アクティブ/オフライン」に区分する。

「同じインスタンス」は自分（ダッシュボード操作者）自身の現在地
（vrchat_session.self_location、Pipelineの"user-location"イベントで更新）と
フレンドのcurrent_locationが一致するかどうかで判定する。

表示件数は`_SIDEBAR_FRIEND_LIMIT`（100人）を上限とし、超える場合はオンライン/
アクティブなフレンドが優先的に残るよう並べ替えてから切り詰める。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecretCipher
from app.models.friend import Friend
from app.schemas.vrchat import parse_instance_privacy_label
from app.services import app_config_service, vrchat_session_service
from app.services.vrchat.client import VRChatClient

# インスタンス人数はVRChat APIへの都度リクエストが必要なため、
# サイドバーの短いポーリング間隔(15秒)に対して過度に叩かないよう軽くキャッシュする。
_INSTANCE_POPULATION_CACHE_TTL_SECONDS = 20.0
_instance_population_cache: dict[str, tuple[float, int]] = {}

# サイドバーに表示するフレンドの上限（多すぎる場合はオンライン/アクティブを優先する）。
_SIDEBAR_FRIEND_LIMIT = 100


@dataclass
class SameInstanceGroup:
    world_name: str | None
    privacy_label: str
    friend_count: int
    instance_total: int | None
    friends: list[Friend]


@dataclass
class SidebarFriendGroups:
    same_instance: SameInstanceGroup | None
    online: list[Friend] = field(default_factory=list)
    active: list[Friend] = field(default_factory=list)
    offline: list[Friend] = field(default_factory=list)


async def _fetch_instance_population(
    db: AsyncSession, cipher: SecretCipher, location: str
) -> int | None:
    now = time.monotonic()
    cached = _instance_population_cache.get(location)
    if cached is not None and now - cached[0] < _INSTANCE_POPULATION_CACHE_TTL_SECONDS:
        return cached[1]

    cookies = await vrchat_session_service.get_decrypted_cookies(db, cipher)
    if cookies is None:
        return None
    auth_cookie, two_factor_cookie = cookies
    user_agent = await app_config_service.get_vrchat_user_agent(db)
    client = VRChatClient(
        user_agent=user_agent, auth_cookie=auth_cookie, two_factor_cookie=two_factor_cookie
    )
    try:
        instance = await client.get_instance(location)
    finally:
        await client.close()
    if instance is None:
        return None

    _instance_population_cache[location] = (now, instance.n_users)
    return instance.n_users


async def get_friend_sidebar_groups(
    db: AsyncSession, cipher: SecretCipher
) -> SidebarFriendGroups:
    session = await vrchat_session_service.get_active_session(db)
    self_location = session.self_location if session else None

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

    same_instance_friends: list[Friend] = []
    online_friends: list[Friend] = []
    active_friends: list[Friend] = []
    offline_friends: list[Friend] = []

    for friend in friends:
        if friend.online_state == "offline":
            offline_friends.append(friend)
        elif friend.online_state == "active":
            active_friends.append(friend)
        elif self_location and friend.current_location == self_location:
            same_instance_friends.append(friend)
        else:
            online_friends.append(friend)

    same_instance_group: SameInstanceGroup | None = None
    if same_instance_friends and self_location:
        instance_total = await _fetch_instance_population(db, cipher, self_location)
        same_instance_group = SameInstanceGroup(
            world_name=same_instance_friends[0].current_world_name,
            privacy_label=parse_instance_privacy_label(self_location),
            friend_count=len(same_instance_friends),
            instance_total=instance_total,
            friends=same_instance_friends,
        )

    return SidebarFriendGroups(
        same_instance=same_instance_group,
        online=online_friends,
        active=active_friends,
        offline=offline_friends,
    )
