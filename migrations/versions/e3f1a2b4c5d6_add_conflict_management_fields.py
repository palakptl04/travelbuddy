"""add_conflict_management_fields

Adds cancel_reason and left_at to trip_members to support:
  - CANCELLED status with optional reason (e.g. 'trip conflict')
  - LEFT status with timestamp

Revision ID: e3f1a2b4c5d6
Revises: d7beffce4e37
Create Date: 2026-06-22 08:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e3f1a2b4c5d6'
down_revision = 'd7beffce4e37'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trip_members', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cancel_reason', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('left_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('trip_members', schema=None) as batch_op:
        batch_op.drop_column('left_at')
        batch_op.drop_column('cancel_reason')
