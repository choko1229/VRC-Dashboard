"""アバターの同期・タグ付け・メモ管理。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.avatar import Avatar
from app.models.avatar_tag import AvatarTag
from app.models.tag import Tag
from app.schemas.vrchat import VRChatAvatar


async def get_avatar(db: AsyncSession, user_id: int, avatar_id: int) -> Avatar | None:
    """指定ユーザーが所有するアバターを取得する（他ユーザーのアバターIDを指定された場合はNone）。"""
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None or avatar.dashboard_user_id != user_id:
        return None
    return avatar


async def get_tag(db: AsyncSession, user_id: int, tag_id: int) -> Tag | None:
    tag = await db.get(Tag, tag_id)
    if tag is None or tag.dashboard_user_id != user_id:
        return None
    return tag


async def list_tags(db: AsyncSession, user_id: int) -> list[Tag]:
    result = await db.execute(
        select(Tag).where(Tag.dashboard_user_id == user_id).order_by(Tag.name)
    )
    return list(result.scalars().all())


async def sync_avatars_from_vrchat(
    db: AsyncSession, user_id: int, avatars: list[VRChatAvatar]
) -> None:
    """VRChatから取得したアバター一覧でavatarテーブルをupsertする。"""
    now = datetime.now(UTC)
    for vrchat_avatar in avatars:
        result = await db.execute(
            select(Avatar).where(
                Avatar.dashboard_user_id == user_id, Avatar.vrchat_avatar_id == vrchat_avatar.id
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = Avatar(
                dashboard_user_id=user_id,
                vrchat_avatar_id=vrchat_avatar.id,
                name=vrchat_avatar.name,
            )
            db.add(row)

        row.name = vrchat_avatar.name
        row.description = vrchat_avatar.description
        row.thumbnail_image_url = vrchat_avatar.thumbnail_image_url
        row.release_status = vrchat_avatar.release_status
        row.version = vrchat_avatar.version
        row.performance_rank = vrchat_avatar.performance_rating or (
            vrchat_avatar.performance_rating_for("standalonewindows")
        )
        row.performance_rank_android = vrchat_avatar.performance_rating_for("android")
        row.performance_rank_ios = vrchat_avatar.performance_rating_for("ios")
        row.created_at_vrchat = vrchat_avatar.created_at
        row.updated_at_vrchat = vrchat_avatar.updated_at
        row.last_synced_at = now

    await db.commit()


async def update_avatar_fields(
    db: AsyncSession,
    user_id: int,
    avatar_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    release_status: str | None = None,
) -> Avatar | None:
    """VRChat側の更新に成功した後、ローカルDBのキャッシュ値を反映する。"""
    avatar = await get_avatar(db, user_id, avatar_id)
    if avatar is None:
        return None
    if name is not None:
        avatar.name = name
    if description is not None:
        avatar.description = description
    if release_status is not None:
        avatar.release_status = release_status
    await db.commit()
    return avatar


async def update_notes(
    db: AsyncSession, user_id: int, avatar_id: int, notes: str | None
) -> Avatar | None:
    avatar = await get_avatar(db, user_id, avatar_id)
    if avatar is None:
        return None
    avatar.notes = notes or None
    await db.commit()
    return avatar


async def add_tag_to_avatar(db: AsyncSession, user_id: int, avatar_id: int, tag_id: int) -> None:
    # 他ユーザーのアバター/タグ同士を関連付けられないよう、両方の所有者を確認する。
    avatar = await get_avatar(db, user_id, avatar_id)
    tag = await get_tag(db, user_id, tag_id)
    if avatar is None or tag is None:
        return
    existing = await db.get(AvatarTag, (avatar_id, tag_id))
    if existing is None:
        db.add(AvatarTag(avatar_id=avatar_id, tag_id=tag_id))
        await db.commit()


async def remove_tag_from_avatar(
    db: AsyncSession, user_id: int, avatar_id: int, tag_id: int
) -> None:
    if await get_avatar(db, user_id, avatar_id) is None:
        return
    existing = await db.get(AvatarTag, (avatar_id, tag_id))
    if existing is not None:
        await db.delete(existing)
        await db.commit()


async def get_avatar_tag_ids(db: AsyncSession, avatar_id: int) -> set[int]:
    result = await db.execute(select(AvatarTag.tag_id).where(AvatarTag.avatar_id == avatar_id))
    return set(result.scalars().all())


async def create_tag(db: AsyncSession, user_id: int, name: str, color: str | None) -> Tag:
    tag = Tag(dashboard_user_id=user_id, name=name, color=color or None)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


async def delete_tag(db: AsyncSession, user_id: int, tag_id: int) -> None:
    tag = await get_tag(db, user_id, tag_id)
    if tag is not None:
        await db.delete(tag)
        await db.commit()


async def count_avatars(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(Avatar).where(Avatar.dashboard_user_id == user_id)
    )
    return result.scalar_one()


async def count_untagged_avatars(db: AsyncSession, user_id: int) -> int:
    """タグが1つも付いていないアバターの件数（準備状況サマリー用）。"""
    result = await db.execute(
        select(Avatar.id)
        .outerjoin(AvatarTag, AvatarTag.avatar_id == Avatar.id)
        .where(Avatar.dashboard_user_id == user_id, AvatarTag.tag_id.is_(None))
    )
    return len(result.scalars().all())
