"""add security session notification fields and indexes

Revision ID: 0004_security_sessions_notifications_indexes
Revises: 0003_add_user_role
Create Date: 2026-06-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_security_sessions_notifications_indexes"
down_revision = "0003_add_user_role"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("users", "failed_login_attempts", server_default=None)

    op.create_table(
        "user_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False, server_default=""),
        sa.Column("ip_address", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("refresh_tokens", sa.Column("device_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_refresh_tokens_device_id_user_devices",
        "refresh_tokens",
        "user_devices",
        ["device_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False, server_default="info"),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_expenses_user_deleted_date_id", "expenses", ["user_id", "deleted", "date", "id"])
    op.create_index("ix_expenses_user_category_date", "expenses", ["user_id", "category", "date"])
    op.create_index("ix_refresh_tokens_user_revoked_expires", "refresh_tokens", ["user_id", "revoked", "expires_at"])
    op.create_index("ix_refresh_tokens_device_id", "refresh_tokens", ["device_id"])
    op.create_index("ix_user_devices_user_id", "user_devices", ["user_id"])
    op.create_index("ix_user_devices_device_fingerprint", "user_devices", ["device_fingerprint"])
    op.create_index("ix_user_devices_last_seen_at", "user_devices", ["last_seen_at"])
    op.create_index("ix_user_devices_user_last_seen", "user_devices", ["user_id", "last_seen_at"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_read", "notifications", ["read"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    op.create_index("ix_notifications_user_read_created", "notifications", ["user_id", "read", "created_at"])


def downgrade():
    op.drop_index("ix_notifications_user_read_created", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_read", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_index("ix_user_devices_user_last_seen", table_name="user_devices")
    op.drop_index("ix_user_devices_last_seen_at", table_name="user_devices")
    op.drop_index("ix_user_devices_device_fingerprint", table_name="user_devices")
    op.drop_index("ix_user_devices_user_id", table_name="user_devices")
    op.drop_index("ix_refresh_tokens_device_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_revoked_expires", table_name="refresh_tokens")
    op.drop_index("ix_expenses_user_category_date", table_name="expenses")
    op.drop_index("ix_expenses_user_deleted_date_id", table_name="expenses")
    op.drop_table("notifications")
    op.drop_constraint("fk_refresh_tokens_device_id_user_devices", "refresh_tokens", type_="foreignkey")
    op.drop_column("refresh_tokens", "device_id")
    op.drop_table("user_devices")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
