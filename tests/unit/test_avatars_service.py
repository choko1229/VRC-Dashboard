"""フェーズ3: アバター同期・タグ付け・メモのユニットテスト。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.avatar import Avatar
from app.models.tag import Tag
from app.schemas.vrchat import VRChatAvatar
from app.services import avatars_service


async def test_sync_avatars_creates_and_updates(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        avatars = [
            VRChatAvatar.model_validate(
                {
                    "id": "avtr_1",
                    "name": "My Avatar",
                    "releaseStatus": "public",
                    "performanceRating": "Good",
                }
            )
        ]
        await avatars_service.sync_avatars_from_vrchat(db, avatars)

        row = (
            await db.execute(select(Avatar).where(Avatar.vrchat_avatar_id == "avtr_1"))
        ).scalar_one()
        assert row.name == "My Avatar"
        assert row.release_status == "public"
        assert row.performance_rank == "Good"

        # 再同期でupdateされる（重複作成されない）
        updated = [
            VRChatAvatar.model_validate(
                {"id": "avtr_1", "name": "Renamed", "releaseStatus": "private"}
            )
        ]
        await avatars_service.sync_avatars_from_vrchat(db, updated)
        rows = (await db.execute(select(Avatar))).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "Renamed"
        assert rows[0].release_status == "private"


async def test_sync_avatars_stores_per_platform_performance_and_metadata(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        avatars = [
            VRChatAvatar.model_validate(
                {
                    "id": "avtr_multi",
                    "name": "Multi Platform Avatar",
                    "description": "テスト用の説明",
                    "releaseStatus": "public",
                    "version": 3,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-02-01T00:00:00Z",
                    "unityPackages": [
                        {"platform": "standalonewindows", "performanceRating": "Good"},
                        {"platform": "android", "performanceRating": "Medium"},
                        {"platform": "ios", "performanceRating": "Poor"},
                    ],
                }
            )
        ]
        await avatars_service.sync_avatars_from_vrchat(db, avatars)

        row = (
            await db.execute(select(Avatar).where(Avatar.vrchat_avatar_id == "avtr_multi"))
        ).scalar_one()
        assert row.description == "テスト用の説明"
        assert row.version == 3
        assert row.performance_rank == "Good"
        assert row.performance_rank_android == "Medium"
        assert row.performance_rank_ios == "Poor"
        assert row.created_at_vrchat is not None
        assert row.updated_at_vrchat is not None


async def test_update_avatar_fields_updates_only_given_fields(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        db.add(
            Avatar(
                vrchat_avatar_id="avtr_edit",
                name="Original",
                description="Original description",
                release_status="private",
            )
        )
        await db.commit()
        avatar = (
            await db.execute(select(Avatar).where(Avatar.vrchat_avatar_id == "avtr_edit"))
        ).scalar_one()

        await avatars_service.update_avatar_fields(db, avatar.id, name="Renamed")
        refreshed = await db.get(Avatar, avatar.id)
        assert refreshed is not None
        assert refreshed.name == "Renamed"
        assert refreshed.description == "Original description"
        assert refreshed.release_status == "private"

        await avatars_service.update_avatar_fields(db, avatar.id, release_status="public")
        refreshed_again = await db.get(Avatar, avatar.id)
        assert refreshed_again is not None
        assert refreshed_again.release_status == "public"
        assert refreshed_again.name == "Renamed"


async def test_notes_and_tags_flow(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        db.add(Avatar(vrchat_avatar_id="avtr_2", name="Test"))
        await db.commit()
        avatar = (
            await db.execute(select(Avatar).where(Avatar.vrchat_avatar_id == "avtr_2"))
        ).scalar_one()

        await avatars_service.update_notes(db, avatar.id, "気に入っている点メモ")
        refreshed = await db.get(Avatar, avatar.id)
        assert refreshed is not None
        assert refreshed.notes == "気に入っている点メモ"

        tag = await avatars_service.create_tag(db, "衣装調整済み", "#22C55E")
        await avatars_service.add_tag_to_avatar(db, avatar.id, tag.id)
        tag_ids = await avatars_service.get_avatar_tag_ids(db, avatar.id)
        assert tag_ids == {tag.id}

        await avatars_service.remove_tag_from_avatar(db, avatar.id, tag.id)
        tag_ids_after = await avatars_service.get_avatar_tag_ids(db, avatar.id)
        assert tag_ids_after == set()


async def test_count_untagged_avatars(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as db:
        db.add_all(
            [
                Avatar(vrchat_avatar_id="a1", name="A1"),
                Avatar(vrchat_avatar_id="a2", name="A2"),
            ]
        )
        await db.commit()
        a1 = (await db.execute(select(Avatar).where(Avatar.vrchat_avatar_id == "a1"))).scalar_one()

        tag = Tag(name="準備完了")
        db.add(tag)
        await db.commit()
        await db.refresh(tag)
        await avatars_service.add_tag_to_avatar(db, a1.id, tag.id)

        untagged = await avatars_service.count_untagged_avatars(db)
        assert untagged == 1
