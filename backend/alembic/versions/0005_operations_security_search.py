"""add operations security search features

Revision ID: 0005_operations_security_search
Revises: 0004_security_sessions_notifications_indexes
Create Date: 2026-06-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_operations_security_search"
down_revision = "0004_security_sessions_notifications_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("two_factor_secret", sa.String(length=64), nullable=True))
    op.alter_column("users", "two_factor_enabled", server_default=None)

    op.add_column("expenses", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("expenses", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("expenses", "archived", server_default=None)
    op.create_index("ix_expenses_archived", "expenses", ["archived"])
    op.create_index("ix_expenses_user_archived_date", "expenses", ["user_id", "archived", "date"])

    op.create_table(
        "backup_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("initiated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )

    op.create_table(
        "scheduled_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scheduled_reports_user_id", "scheduled_reports", ["user_id"])
    op.create_index("ix_scheduled_reports_next_run_at", "scheduled_reports", ["next_run_at"])
    op.create_index("ix_scheduled_reports_active_next_run", "scheduled_reports", ["active", "next_run_at"])

    op.create_table(
        "queue_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_name", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_queue_jobs_task_name", "queue_jobs", ["task_name"])
    op.create_index("ix_queue_jobs_status", "queue_jobs", ["status"])
    op.create_index("ix_queue_jobs_scheduled_for", "queue_jobs", ["scheduled_for"])
    op.create_index("ix_queue_jobs_status_scheduled", "queue_jobs", ["status", "scheduled_for"])

    op.create_table(
        "feature_flags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=80), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("audience", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feature_flags_key", "feature_flags", ["key"])

    op.create_table(
        "archive_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("archived_before", sa.Date(), nullable=False),
        sa.Column("archived_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_archive_records_user_id", "archive_records", ["user_id"])


def downgrade():
    op.drop_index("ix_archive_records_user_id", table_name="archive_records")
    op.drop_table("archive_records")
    op.drop_index("ix_feature_flags_key", table_name="feature_flags")
    op.drop_table("feature_flags")
    op.drop_index("ix_queue_jobs_status_scheduled", table_name="queue_jobs")
    op.drop_index("ix_queue_jobs_scheduled_for", table_name="queue_jobs")
    op.drop_index("ix_queue_jobs_status", table_name="queue_jobs")
    op.drop_index("ix_queue_jobs_task_name", table_name="queue_jobs")
    op.drop_table("queue_jobs")
    op.drop_index("ix_scheduled_reports_active_next_run", table_name="scheduled_reports")
    op.drop_index("ix_scheduled_reports_next_run_at", table_name="scheduled_reports")
    op.drop_index("ix_scheduled_reports_user_id", table_name="scheduled_reports")
    op.drop_table("scheduled_reports")
    op.drop_table("backup_records")
    op.drop_index("ix_expenses_user_archived_date", table_name="expenses")
    op.drop_index("ix_expenses_archived", table_name="expenses")
    op.drop_column("expenses", "archived_at")
    op.drop_column("expenses", "archived")
    op.drop_column("users", "two_factor_secret")
    op.drop_column("users", "two_factor_enabled")
