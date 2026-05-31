"""create refresh_tokens table

Revision ID: 0001_add_refresh_tokens
Revises: 
Create Date: 2026-05-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_add_refresh_tokens'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('jti', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), index=True),
        sa.Column('token_hash', sa.String(128), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('expires_at', sa.DateTime(timezone=True), index=True),
        sa.Column('revoked', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table('refresh_tokens')
