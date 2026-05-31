"""add deleted/deleted_at to expenses

Revision ID: 0002_add_expense_soft_delete
Revises: 0001_add_refresh_tokens
Create Date: 2026-05-28 00:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002_add_expense_soft_delete'
down_revision = '0001_add_refresh_tokens'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('expenses', sa.Column('deleted', sa.Boolean, nullable=False, server_default=sa.text('false')))
    op.add_column('expenses', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('expenses', 'deleted_at')
    op.drop_column('expenses', 'deleted')
