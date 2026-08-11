from datetime import date, datetime, UTC
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CategoryRead(BaseModel):
    id: int
    name: str
    budget: Decimal
    color: str

    model_config = ConfigDict(from_attributes=True)


class CategoryUpdate(BaseModel):
    budget: Decimal = Field(ge=0)


class ExpenseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    amount: Decimal = Field(gt=0)
    category: str = Field(min_length=1, max_length=80)
    date: date

    @field_validator("date")
    @classmethod
    def date_not_in_far_future(cls, v: date) -> date:
        if v > datetime.now(UTC).date():
            raise ValueError("Expense date cannot be in the future")
        return v


class ExpenseRead(ExpenseCreate):
    id: int
    deleted: bool | None = False
    deleted_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ExpenseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    amount: Decimal | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    date: date | None = None

    @field_validator("date")
    @classmethod
    def date_not_in_far_future(cls, v: date | None) -> date | None:
        if v is not None and v > datetime.now(UTC).date():
            raise ValueError("Expense date cannot be in the future")
        return v


class GoalUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target: Decimal = Field(gt=0)
    saved: Decimal = Field(ge=0)


class GoalRead(GoalUpdate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class RecurringExpenseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    amount: Decimal = Field(gt=0)
    category: str = Field(min_length=1, max_length=80)
    frequency: str = Field(pattern=r"^(monthly|weekly|yearly)$")
    day_of_month: int | None = Field(None, ge=1, le=31)
    day_of_week: int | None = Field(None, ge=0, le=6)

    @model_validator(mode="after")
    def validate_recurring_schedule(self):
        if self.frequency == "weekly" and self.day_of_week is None:
            raise ValueError("day_of_week is required for weekly recurring expenses")
        if self.frequency in {"monthly", "yearly"} and self.day_of_month is None:
            raise ValueError("day_of_month is required for monthly and yearly recurring expenses")
        return self


class RecurringExpenseRead(RecurringExpenseCreate):
    id: int
    last_generated_at: date | None = None

    model_config = ConfigDict(from_attributes=True)


class RecurringExpenseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    amount: Decimal | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    frequency: str | None = Field(default=None, pattern=r"^(monthly|weekly|yearly)$")
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    day_of_week: int | None = Field(default=None, ge=0, le=6)

    @model_validator(mode="after")
    def validate_recurring_schedule(self):
        if self.frequency == "weekly" and self.day_of_week is None:
            raise ValueError("day_of_week is required for weekly recurring expenses")
        if self.frequency in {"monthly", "yearly"} and self.day_of_month is None:
            raise ValueError("day_of_month is required for monthly and yearly recurring expenses")
        return self




class ProfileUpdate(BaseModel):
    allowance: Decimal = Field(ge=0)
    preferred_range: str | None = Field(default=None, max_length=20)
    custom_range_start: date | None = None
    custom_range_end: date | None = None


class ProfileRead(BaseModel):
    id: int
    name: str
    first_name: str
    last_name: str
    gender: str
    email: str
    email_verified: bool
    two_factor_enabled: bool = False
    role: str
    allowance: Decimal
    preferred_range: str
    custom_range_start: date | None = None
    custom_range_end: date | None = None

    model_config = ConfigDict(from_attributes=True)


class AccountSecurityRead(BaseModel):
    failed_login_attempts: int
    locked_until: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserSettingsRead(BaseModel):
    country: str
    savings_currencies: list[dict]

    model_config = ConfigDict(from_attributes=True)


class AppStateRead(BaseModel):
    profile: ProfileRead
    categories: list[CategoryRead]
    expenses: list[ExpenseRead]
    goal: GoalRead
    settings: UserSettingsRead


class SettingsUpdate(BaseModel):
    country: str | None = None
    savings_currencies: list[dict] | None = None


class SignupRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    gender: str = Field(min_length=1, max_length=32, pattern=r"^(female|male|non_binary|prefer_not_to_say)$")
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def password_must_be_reasonably_strong(cls, value: str) -> str:
        has_letter = any(character.isalpha() for character in value)
        has_number = any(character.isdigit() for character in value)
        if not has_letter or not has_number:
            raise ValueError("Password must include at least one letter and one number")

        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    profile: ProfileRead


class AuthResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    profile: ProfileRead | None = None
    requires_two_factor: bool = False
    two_factor_token: str | None = None


class VerifyEmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendVerificationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=20, max_length=1024)
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def new_password_must_be_reasonably_strong(cls, value: str) -> str:
        has_letter = any(character.isalpha() for character in value)
        has_number = any(character.isdigit() for character in value)
        if not has_letter or not has_number:
            raise ValueError("Password must include at least one letter and one number")
        return value


class TwoFactorSetupRead(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFactorEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TwoFactorDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TwoFactorVerifyRequest(BaseModel):
    two_factor_token: str = Field(min_length=20)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MessageRead(BaseModel):
    message: str


class HealthRead(BaseModel):
    status: str
    api_version: str
    request_id: str | None = None
    correlation_id: str | None = None


class DependencyHealthRead(HealthRead):
    dependency: str
    latency_ms: float | None = None
    detail: str | None = None


class NotificationRead(BaseModel):
    id: int
    type: str
    title: str
    message: str
    read: bool
    created_at: datetime
    read_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SessionRead(BaseModel):
    id: int
    jti: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked: bool
    device_id: int | None = None
    user_agent: str | None = None
    ip_address: str | None = None


class DeviceRead(BaseModel):
    id: int
    user_agent: str
    ip_address: str
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExpenseExportEmailRequest(BaseModel):
    email: str | None = None
    format: str = Field(default="csv", pattern=r"^(csv)$")


class PaginationInfo(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ExpenseListRead(BaseModel):
    expenses: list[ExpenseRead]
    pagination: PaginationInfo


class BackupRead(BaseModel):
    id: int
    filename: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    size_bytes: int
    detail: str

    model_config = ConfigDict(from_attributes=True)


class ScheduledReportCreate(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    frequency: str = Field(default="weekly", pattern=r"^(daily|weekly|monthly)$")
    format: str = Field(default="csv", pattern=r"^(csv)$")


class ScheduledReportRead(BaseModel):
    id: int
    email: str
    frequency: str
    format: str
    active: bool
    next_run_at: datetime
    last_run_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeatureFlagUpsert(BaseModel):
    description: str = ""
    enabled: bool = False
    audience: dict[str, object] = Field(default_factory=dict)


class FeatureFlagRead(FeatureFlagUpsert):
    key: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueueJobCreate(BaseModel):
    task_name: str = Field(min_length=1, max_length=80)
    payload: dict[str, object] = Field(default_factory=dict)
    scheduled_for: datetime | None = None


class QueueJobRead(BaseModel):
    id: int
    task_name: str
    payload: dict[str, object]
    status: str
    attempts: int
    max_attempts: int
    scheduled_for: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str

    model_config = ConfigDict(from_attributes=True)


class ArchiveRequest(BaseModel):
    archived_before: date


class ArchiveRead(BaseModel):
    id: int
    archived_before: date
    archived_count: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CategoryAnalytics(BaseModel):
    category: str
    total_amount: Decimal
    transaction_count: int


class AdminDashboardRead(BaseModel):
    total_users: int
    verified_users: int
    total_expenses: int
    total_spend: Decimal
    top_categories: list[CategoryAnalytics]

    model_config = ConfigDict(from_attributes=True)

class TotalBalanceRead(BaseModel):
    home_currency: str
    total_converted_balance: Decimal
