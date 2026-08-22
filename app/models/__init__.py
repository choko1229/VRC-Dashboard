"""全モデルをインポートし、Base.metadataに登録する（Alembicのautogenerate用）。"""

from app.models.app_setting import AppSetting
from app.models.avatar import Avatar
from app.models.avatar_tag import AvatarTag
from app.models.dashboard_session import DashboardSession
from app.models.dashboard_user import DashboardUser
from app.models.discord_allowlist_entry import DiscordAllowlistEntry
from app.models.friend import Friend
from app.models.friend_group import FriendGroup
from app.models.friend_group_membership import FriendGroupMembership
from app.models.friend_notification_pref import FriendNotificationPref
from app.models.friend_presence_event import FriendPresenceEvent
from app.models.schedule_event import ScheduleEvent
from app.models.sync_cursor import SyncCursor
from app.models.tag import Tag
from app.models.vrchat_session import VRChatSession
from app.models.web_push_subscription import WebPushSubscription

__all__ = [
    "AppSetting",
    "Avatar",
    "AvatarTag",
    "DashboardSession",
    "DashboardUser",
    "DiscordAllowlistEntry",
    "Friend",
    "FriendGroup",
    "FriendGroupMembership",
    "FriendNotificationPref",
    "FriendPresenceEvent",
    "ScheduleEvent",
    "SyncCursor",
    "Tag",
    "VRChatSession",
    "WebPushSubscription",
]
