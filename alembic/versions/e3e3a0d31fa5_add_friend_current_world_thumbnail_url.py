"""add friend current_world_thumbnail_url

Revision ID: e3e3a0d31fa5
Revises: ff8deb1a5e2c
Create Date: 2026-08-23 17:52:38.785334

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3e3a0d31fa5'
down_revision: Union[str, Sequence[str], None] = 'ff8deb1a5e2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('friend', sa.Column('current_world_thumbnail_url', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('friend', 'current_world_thumbnail_url')
