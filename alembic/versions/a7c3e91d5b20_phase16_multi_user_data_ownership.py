"""phase16: multi user data ownership

複数人利用に対応するため、ユーザー単位のデータを持つ全テーブルに所有者
（dashboard_user_id）を追加し、VRChat由来の一意キーを「所有者単位の一意」に変更する。
既存データは、単一ユーザー時代の利用者＝管理者（管理者がいなければ最初のユーザー）の所有とする。

Revision ID: a7c3e91d5b20
Revises: 49da53f935d1
Create Date: 2026-09-27 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c3e91d5b20'
down_revision: Union[str, Sequence[str], None] = '49da53f935d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# SQLiteのbatchモードで、名前の無いUNIQUE制約（旧マイグレーションのsa.UniqueConstraint）を
# 名前で削除できるようにするための命名規則。
_NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}

_OWNED_TABLES = (
    "vrchat_session",
    "friend",
    "friend_group",
    "avatar",
    "tag",
    "schedule_event",
    "vrchat_notification",
    "game_log_instance",
    "game_log_agent_token",
    "agent_command",
)

# 所有者を決められない（ダッシュボードユーザーが1人もいない）場合に、親と一緒に消す子テーブル。
_CHILD_TABLES = (
    "friend_presence_event",
    "friend_notification_pref",
    "friend_group_membership",
    "avatar_tag",
    "game_log_event",
)


def _backfill_owner_id(conn: sa.engine.Connection) -> int | None:
    return conn.execute(
        sa.text("SELECT id FROM dashboard_user ORDER BY is_admin DESC, id ASC LIMIT 1")
    ).scalar()


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    owner_id = _backfill_owner_id(conn)

    if owner_id is not None:
        # is_admin列（phase6）より前から使っていた環境では管理者が1人もおらず、複数人利用に必要な
        # 許可リスト管理（ユーザー招待）が誰にもできないため、既存データの所有者を管理者にする。
        conn.execute(
            sa.text(
                "UPDATE dashboard_user SET is_admin = 1 WHERE id = :owner_id"
                " AND NOT EXISTS (SELECT 1 FROM dashboard_user WHERE is_admin = 1)"
            ),
            {"owner_id": owner_id},
        )
    else:
        # 所有者を割り当てられないデータは残しておけないため削除する
        # （ユーザーが1人もいない状態ではVRChat連携・ゲームログ取込もできないため、通常は空）。
        for table in (*_CHILD_TABLES, *_OWNED_TABLES):
            conn.execute(sa.text(f"DELETE FROM {table}"))

    for table in _OWNED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('dashboard_user_id', sa.Integer(), nullable=True))
        if owner_id is not None:
            conn.execute(
                sa.text(f"UPDATE {table} SET dashboard_user_id = :owner_id"),
                {"owner_id": owner_id},
            )
        with op.batch_alter_table(
            table, schema=None, naming_convention=_NAMING_CONVENTION
        ) as batch_op:
            batch_op.alter_column('dashboard_user_id', existing_type=sa.Integer(), nullable=False)
            batch_op.create_index(
                batch_op.f(f'ix_{table}_dashboard_user_id'), ['dashboard_user_id'], unique=False
            )
            batch_op.create_foreign_key(
                batch_op.f(f'fk_{table}_dashboard_user_id_dashboard_user'),
                'dashboard_user',
                ['dashboard_user_id'],
                ['id'],
                ondelete='CASCADE',
            )

            # VRChat由来の一意キーを、所有者単位の一意に変更する。
            if table == "friend":
                batch_op.drop_index('ix_friend_vrchat_user_id')
                batch_op.create_index('ix_friend_vrchat_user_id', ['vrchat_user_id'], unique=False)
                batch_op.create_unique_constraint(
                    'uq_friend_owner', ['dashboard_user_id', 'vrchat_user_id']
                )
            elif table == "avatar":
                batch_op.drop_index('ix_avatar_vrchat_avatar_id')
                batch_op.create_index(
                    'ix_avatar_vrchat_avatar_id', ['vrchat_avatar_id'], unique=False
                )
                batch_op.create_unique_constraint(
                    'uq_avatar_owner', ['dashboard_user_id', 'vrchat_avatar_id']
                )
            elif table == "vrchat_notification":
                batch_op.drop_index('ix_vrchat_notification_vrchat_notification_id')
                batch_op.create_index(
                    'ix_vrchat_notification_vrchat_notification_id',
                    ['vrchat_notification_id'],
                    unique=False,
                )
                batch_op.create_unique_constraint(
                    'uq_vrchat_notification_owner', ['dashboard_user_id', 'vrchat_notification_id']
                )
            elif table == "friend_group":
                batch_op.drop_constraint('uq_friend_group_vrchat_group_id', type_='unique')
                batch_op.create_unique_constraint(
                    'uq_friend_group_owner', ['dashboard_user_id', 'vrchat_group_id']
                )
            elif table == "tag":
                batch_op.drop_constraint('uq_tag_name', type_='unique')
                batch_op.create_unique_constraint('uq_tag_owner', ['dashboard_user_id', 'name'])
            elif table == "schedule_event":
                batch_op.drop_constraint('uq_schedule_event_vrchat_event_id', type_='unique')
                batch_op.create_unique_constraint(
                    'uq_schedule_event_owner', ['dashboard_user_id', 'vrchat_event_id']
                )

    # sync_cursorは主キー自体が変わる（resource_name → (dashboard_user_id, resource_name)）。
    # 中身は「最終同期日時」だけで次回同期時に作り直されるため、作り直しで対応する。
    op.drop_table('sync_cursor')
    op.create_table(
        'sync_cursor',
        sa.Column('dashboard_user_id', sa.Integer(), nullable=False),
        sa.Column('resource_name', sa.String(length=50), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success', sa.Boolean(), nullable=False),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['dashboard_user_id'], ['dashboard_user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('dashboard_user_id', 'resource_name'),
    )


def downgrade() -> None:
    """Downgrade schema.

    複数ユーザー分のデータが入っている場合、旧来の全体一意制約に違反するため失敗しうる
    （その場合は重複データを手動で整理してから実行すること）。
    """
    op.drop_table('sync_cursor')
    op.create_table(
        'sync_cursor',
        sa.Column('resource_name', sa.String(length=50), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success', sa.Boolean(), nullable=False),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('resource_name'),
    )

    for table in reversed(_OWNED_TABLES):
        with op.batch_alter_table(
            table, schema=None, naming_convention=_NAMING_CONVENTION
        ) as batch_op:
            if table == "friend":
                batch_op.drop_constraint('uq_friend_owner', type_='unique')
                batch_op.drop_index('ix_friend_vrchat_user_id')
                batch_op.create_index('ix_friend_vrchat_user_id', ['vrchat_user_id'], unique=True)
            elif table == "avatar":
                batch_op.drop_constraint('uq_avatar_owner', type_='unique')
                batch_op.drop_index('ix_avatar_vrchat_avatar_id')
                batch_op.create_index(
                    'ix_avatar_vrchat_avatar_id', ['vrchat_avatar_id'], unique=True
                )
            elif table == "vrchat_notification":
                batch_op.drop_constraint('uq_vrchat_notification_owner', type_='unique')
                batch_op.drop_index('ix_vrchat_notification_vrchat_notification_id')
                batch_op.create_index(
                    'ix_vrchat_notification_vrchat_notification_id',
                    ['vrchat_notification_id'],
                    unique=True,
                )
            elif table == "friend_group":
                batch_op.drop_constraint('uq_friend_group_owner', type_='unique')
                batch_op.create_unique_constraint(
                    'uq_friend_group_vrchat_group_id', ['vrchat_group_id']
                )
            elif table == "tag":
                batch_op.drop_constraint('uq_tag_owner', type_='unique')
                batch_op.create_unique_constraint('uq_tag_name', ['name'])
            elif table == "schedule_event":
                batch_op.drop_constraint('uq_schedule_event_owner', type_='unique')
                batch_op.create_unique_constraint(
                    'uq_schedule_event_vrchat_event_id', ['vrchat_event_id']
                )

            batch_op.drop_constraint(
                batch_op.f(f'fk_{table}_dashboard_user_id_dashboard_user'), type_='foreignkey'
            )
            batch_op.drop_index(batch_op.f(f'ix_{table}_dashboard_user_id'))
            batch_op.drop_column('dashboard_user_id')
