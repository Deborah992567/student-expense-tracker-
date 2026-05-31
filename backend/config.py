from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).with_name(".env")


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://student_expense:student_expense@localhost:5432/student_expense"
    redis_url: str = "redis://localhost:6379/0"
    api_cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000,null"
    secret_key: str = "change-this-dev-secret"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cookie_secure: bool = False
    login_max_attempts: int = 5
    login_lockout_minutes: int = 10
    email_verification_minutes: int = 10
    email_verification_max_attempts: int = 5
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "no-reply@student-spend.local"
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout: int = 10

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
