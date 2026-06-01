"""add role to users

Revision ID: 0003_add_user_role
Revises: 0002_add_expense_soft_delete
Create Date: 2026-06-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0003_add_user_role'
down_revision = '0002_add_expense_soft_delete'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('role', sa.String(length=20), nullable=False, server_default='student'),
    )
    op.execute("UPDATE users SET role = 'student' WHERE role IS NULL")
    op.alter_column('users', 'role', server_default=None)


def downgrade():
    op.drop_column('users', 'role')
