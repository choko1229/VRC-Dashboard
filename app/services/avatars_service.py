"""アバターの同期・タグ付け・メモ管理。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.avatar import Avatar
from app.models.avatar_tag import AvatarTag
from app.models.tag import Tag
from app.schemas.vrchat import VRChatAvatar


async def sync_avatars_from_vrchat(db: AsyncSession, avatars: list[VRChatAvatar]) -> None:
    """VRChatから取得したアバター一覧でavatarテーブルをupsertする。"""
    now = datetime.now(UTC)
    for vrchat_avatar in avatars:
        result = await db.execute(
            select(Avatar).where(Avatar.vrchat_avatar_id == vrchat_avatar.id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = Avatar(vrchat_avatar_id=vrchat_avatar.id, name=vrchat_avatar.name)
            db.add(row)

        row.name = vrchat_avatar.name
        row.thumbnail_image_url = vrchat_avatar.thumbnail_image_url
        row.release_status = vrchat_avatar.release_status
        row.performance_rank = vrchat_avatar.performance_rating
        row.updated_at_vrchat = vrchat_avatar.updated_at
        row.last_synced_at = now

    await db.commit()


async def update_notes(db: AsyncSession, avatar_id: int, notes: str | None) -> Avatar | None:
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        return None
    avatar.notes = notes or None
    await db.commit()
    return avatar


async def add_tag_to_avatar(db: AsyncSession, avatar_id: int, tag_id: int) -> None:
    existing = await db.get(AvatarTag, (avatar_id, tag_id))
    if existing is None:
        db.add(AvatarTag(avatar_id=avatar_id, tag_id=tag_id))
        await db.commit()


async def remove_tag_from_avatar(db: AsyncSession, avatar_id: int, tag_id: int) -> None:
    existing = await db.get(AvatarTag, (avatar_id, tag_id))
    if existing is not None:
        await db.delete(existing)
        await db.commit()


async def get_avatar_tag_ids(db: AsyncSession, avatar_id: int) -> set[int]:
    result = await db.execute(select(AvatarTag.tag_id).where(AvatarTag.avatar_id == avatar_id))
    return set(result.scalars().all())


async def create_tag(db: AsyncSession, name: str, color: str | None) -> Tag:
    tag = Tag(name=name, color=color or None)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


async def delete_tag(db: AsyncSession, tag_id: int) -> None:
    tag = await db.get(Tag, tag_id)
    if tag is not None:
        await db.delete(tag)
        await db.commit()


async def count_untagged_avatars(db: AsyncSession) -> int:
    """タグが1つも付いていないアバターの件数（準備状況サマリー用）。"""
    result = await db.execute(
        select(Avatar.id).outerjoin(AvatarTag, AvatarTag.avatar_id == Avatar.id).where(
            AvatarTag.tag_id.is_(None)
        )
    )
    return len(result.scalars().all())
