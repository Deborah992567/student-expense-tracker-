from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class ExpenseRead(ExpenseCreate):
    id: int
    deleted: bool | None = False
    deleted_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class GoalUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target: Decimal = Field(gt=0)
    saved: Decimal = Field(ge=0)


class GoalRead(GoalUpdate):
    id: int

    model_config = ConfigDict(from_attributes=True)


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
    allowance: Decimal
    preferred_range: str
    custom_range_start: date | None = None
    custom_range_end: date | None = None

    model_config = ConfigDict(from_attributes=True)


class AppStateRead(BaseModel):
    profile: ProfileRead
    categories: list[CategoryRead]
    expenses: list[ExpenseRead]
    goal: GoalRead
    settings: UserSettingsRead


class UserSettingsRead(BaseModel):
    country: str
    savings_currencies: list[dict]

    model_config = ConfigDict(from_attributes=True)


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


class VerifyEmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendVerificationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class MessageRead(BaseModel):
    message: str


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

class CategoryAnalytics(BaseModel):
    category: str
    total_amount: Decimal
    transaction_count: int
