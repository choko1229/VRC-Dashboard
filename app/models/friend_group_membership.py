"""フレンドとフレンドグループの多対多関連。"""

from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FriendGroupMembership(Base):
    __tablename__ = "friend_group_membership"

    friend_id: Mapped[int] = mapped_column(
        ForeignKey("friend.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("friend_group.id", ondelete="CASCADE"), primary_key=True, index=True
    )
