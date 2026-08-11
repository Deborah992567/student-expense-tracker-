from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    first_name: Mapped[str] = mapped_column(String(80), default="")
    last_name: Mapped[str] = mapped_column(String(80), default="")
    gender: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_secret: Mapped[str] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="student", nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    allowance: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=950)
    preferred_range: Mapped[str] = mapped_column(String(20), default="week")
    custom_range_start: Mapped[date] = mapped_column(Date, nullable=True)
    custom_range_end: Mapped[date] = mapped_column(Date, nullable=True)

    categories: Mapped[list["Category"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    recurring_expenses: Mapped[list["RecurringExpense"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    goals: Mapped[list["Goal"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    email_codes: Mapped[list["EmailVerificationCode"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    settings: Mapped["UserSettings"] = relationship(back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    devices: Mapped[list["UserDevice"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    scheduled_reports: Mapped[list["ScheduledReport"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    savings_challenges: Mapped[list["SavingsChallenge"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    split_groups: Mapped[list["SplitGroup"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    group_budgets: Mapped[list["GroupBudget"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    budget: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    color: Mapped[str] = mapped_column(String(16))

    user: Mapped[User] = relationship(back_populates="categories")


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        Index("ix_expenses_user_deleted_date_id", "user_id", "deleted", "date", "id"),
        Index("ix_expenses_user_category_date", "user_id", "category", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    category: Mapped[str] = mapped_column(String(80), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    receipt_path: Mapped[str] = mapped_column(String(500), nullable=True)
    tax_deductible: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_category: Mapped[str] = mapped_column(String(80), nullable=True)

    user: Mapped[User] = relationship(back_populates="expenses")


class RecurringExpense(Base):
    __tablename__ = "recurring_expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    category: Mapped[str] = mapped_column(String(80))
    frequency: Mapped[str] = mapped_column(String(20))  # 'monthly', 'weekly'
    day_of_month: Mapped[int] = mapped_column(nullable=True)  # 1-31
    day_of_week: Mapped[int] = mapped_column(nullable=True)   # 0-6 (Mon-Sun)
    last_generated_at: Mapped[date] = mapped_column(Date, nullable=True)

    user: Mapped[User] = relationship(back_populates="recurring_expenses")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    target: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    saved: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    user: Mapped[User] = relationship(back_populates="goals")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    country: Mapped[str] = mapped_column(String(80), default="United States")
    savings_currencies: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    dark_mode: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="settings")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_revoked_expires", "user_id", "revoked", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("user_devices.id", ondelete="SET NULL"), nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
    device: Mapped["UserDevice"] = relationship(back_populates="refresh_tokens")


class UserDevice(Base):
    __tablename__ = "user_devices"
    __table_args__ = (
        Index("ix_user_devices_user_last_seen", "user_id", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_agent: Mapped[str] = mapped_column(Text, default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[User] = relationship(back_populates="devices")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="device")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "read", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40), default="info", nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="notifications")


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(128), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="email_codes")


class BackupRecord(Base):
    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    size_bytes: Mapped[int] = mapped_column(default=0, nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    initiated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ScheduledReport(Base):
    __tablename__ = "scheduled_reports"
    __table_args__ = (
        Index("ix_scheduled_reports_active_next_run", "active", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), default="weekly", nullable=False)
    format: Mapped[str] = mapped_column(String(10), default="csv", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="scheduled_reports")


class QueueJob(Base):
    __tablename__ = "queue_jobs"
    __table_args__ = (
        Index("ix_queue_jobs_status_scheduled", "status", "scheduled_for"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=3, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    audience: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArchiveRecord(Base):
    __tablename__ = "archive_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    archived_before: Mapped[date] = mapped_column(Date, nullable=False)
    archived_count: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SavingsChallenge(Base):
    __tablename__ = "savings_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    current_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    streak_days: Mapped[int] = mapped_column(default=0, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_contribution_date: Mapped[date] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="savings_challenges")


class SplitGroup(Base):
    __tablename__ = "split_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="split_groups")
    members: Mapped[list["SplitMember"]] = relationship(back_populates="group", cascade="all, delete-orphan")
    expenses: Mapped[list["SplitExpense"]] = relationship(back_populates="group", cascade="all, delete-orphan")


class SplitMember(Base):
    __tablename__ = "split_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("split_groups.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), nullable=True)

    group: Mapped[SplitGroup] = relationship(back_populates="members")


class SplitExpense(Base):
    __tablename__ = "split_expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("split_groups.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    paid_by_member_id: Mapped[int] = mapped_column(ForeignKey("split_members.id", ondelete="CASCADE"))
    split_type: Mapped[str] = mapped_column(String(20), default="equal")
    splits: Mapped[dict] = mapped_column(JSON, default=dict)
    date: Mapped[date] = mapped_column(Date)
    settled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[SplitGroup] = relationship(back_populates="expenses")
    paid_by: Mapped[SplitMember] = relationship()


class GroupBudget(Base):
    __tablename__ = "group_budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    total_budget: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    spent: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    members: Mapped[dict] = mapped_column(JSON, default=dict)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="group_budgets")


class TaxCategory(Base):
    __tablename__ = "tax_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    deductible_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=100)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth_key: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
