"""add_join_deadline_open_roster_contact_log

Revision ID: a1b2c3d4e5f6
Revises: 5afe88814f04
Create Date: 2026-06-20 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '5afe88814f04'
branch_labels = None
depends_on = None


def upgrade():
    # ── Add join_deadline to trips ──────────────────────────────────────────
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.add_column(sa.Column('join_deadline', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('open_roster', sa.Boolean(), nullable=True,
                                      server_default=sa.text('0')))

    # ── Create contact_access_logs ──────────────────────────────────────────
    op.create_table(
        'contact_access_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('viewer_id', sa.Integer(), nullable=False),
        sa.Column('target_user_id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('viewed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['viewer_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('contact_access_logs', schema=None) as batch_op:
        batch_op.create_index('ix_cal_viewer_trip', ['viewer_id', 'trip_id'], unique=False)
        batch_op.create_index('ix_cal_target_trip', ['target_user_id', 'trip_id'], unique=False)


def downgrade():
    with op.batch_alter_table('contact_access_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_cal_target_trip')
        batch_op.drop_index('ix_cal_viewer_trip')

    op.drop_table('contact_access_logs')

    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.drop_column('open_roster')
        batch_op.drop_column('join_deadline')
