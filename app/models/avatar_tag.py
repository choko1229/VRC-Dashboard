"""アバターとタグの多対多関連。"""

from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AvatarTag(Base):
    __tablename__ = "avatar_tag"

    avatar_id: Mapped[int] = mapped_column(
        ForeignKey("avatar.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True, index=True
    )
