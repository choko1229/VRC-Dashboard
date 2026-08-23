"""VRChat REST APIからのフル再同期（ログイン直後のブートストラップ・手動再同期の両方で使う）。"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import avatars_service, friends_service, schedule_service, sync_cursor_service
from app.services.vrchat.client import VRChatAPIError, VRChatClient

logger = logging.getLogger(__name__)

_FRIENDS_RESOURCE_NAME = "friends_bootstrap"
_AVATARS_RESOURCE_NAME = "avatars"
_CALENDAR_RESOURCE_NAME = "vrchat_calendar"


async def full_friends_sync(db: AsyncSession, client: VRChatClient) -> None:
    """フレンド一覧・お気に入りグループ・所属関係をVRChatから取得しDBへ反映する。"""
    try:
        online_friends = await client.get_friends(offline=False)
        offline_friends = await client.get_friends(offline=True)
        await friends_service.bootstrap_friends_from_vrchat(
            db, client, online_friends=online_friends, offline_friends=offline_friends
        )

        groups = await client.get_favorite_friend_groups()
        favorites = await client.get_favorite_friends()
        await friends_service.sync_favorite_groups(db, groups=groups, favorites=favorites)

        await friends_service.sync_friend_profile_details(db, client)
    except VRChatAPIError as exc:
        logger.warning("フレンド同期に失敗しました: %s", exc)
        await sync_cursor_service.mark_synced(
            db, _FRIENDS_RESOURCE_NAME, success=False, error=str(exc)
        )
        raise

    await sync_cursor_service.mark_synced(db, _FRIENDS_RESOURCE_NAME, success=True)


async def full_avatars_sync(db: AsyncSession, client: VRChatClient) -> None:
    """自分のアバター一覧をVRChatから取得しDBへ反映する。"""
    try:
        avatars = await client.get_own_avatars()
        await avatars_service.sync_avatars_from_vrchat(db, avatars)
    except VRChatAPIError as exc:
        logger.warning("アバター同期に失敗しました: %s", exc)
        await sync_cursor_service.mark_synced(
            db, _AVATARS_RESOURCE_NAME, success=False, error=str(exc)
        )
        raise

    await sync_cursor_service.mark_synced(db, _AVATARS_RESOURCE_NAME, success=True)


async def import_group_calendar(
    db: AsyncSession, client: VRChatClient, vrchat_group_id: str
) -> int:
    """指定したVRChatグループのカレンダーイベントを取込む。戻り値は新規取込件数。"""
    try:
        events = await client.get_group_calendar_events(vrchat_group_id)
        imported = await schedule_service.import_calendar_events(db, events)
    except VRChatAPIError as exc:
        logger.warning("VRChatカレンダー取込に失敗しました: %s", exc)
        await sync_cursor_service.mark_synced(
            db, _CALENDAR_RESOURCE_NAME, success=False, error=str(exc)
        )
        raise

    await sync_cursor_service.mark_synced(db, _CALENDAR_RESOURCE_NAME, success=True)
    return imported
