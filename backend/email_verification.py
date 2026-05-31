import hashlib
import hmac
import logging
import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import models
from backend.config import get_settings
from backend.logging_config import get_logger, get_security_logger

logger = get_logger(__name__)
security_logger = get_security_logger()


class EmailDeliveryError(RuntimeError):
    pass


def create_verification_code(db: Session, user: models.User) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = datetime.now(UTC) + timedelta(minutes=get_settings().email_verification_minutes)
    db.add(
        models.EmailVerificationCode(
            user_id=user.id,
            code_hash=hash_verification_code(user.email, code),
            expires_at=expires_at,
        ),
    )
    db.commit()
    logger.info("Verification code created for user_id=%s, email=%s, expires_at=%s", 
                user.id, user.email, expires_at.isoformat())
    return code


def hash_verification_code(email: str, code: str) -> str:
    secret = get_settings().secret_key.encode("utf-8")
    value = f"{email.lower().strip()}:{code}".encode("utf-8")
    return hmac.new(secret, value, hashlib.sha256).hexdigest()


def latest_active_code(db: Session, user: models.User, code: str) -> models.EmailVerificationCode | None:
    code_hash = hash_verification_code(user.email, code)
    return db.scalar(
        select(models.EmailVerificationCode)
        .where(
            models.EmailVerificationCode.user_id == user.id,
            models.EmailVerificationCode.code_hash == code_hash,
            models.EmailVerificationCode.used_at.is_(None),
        )
        .order_by(models.EmailVerificationCode.id.desc()),
    )


def latest_pending_code(db: Session, user: models.User) -> models.EmailVerificationCode | None:
    return db.scalar(
        select(models.EmailVerificationCode)
        .where(
            models.EmailVerificationCode.user_id == user.id,
            models.EmailVerificationCode.used_at.is_(None),
        )
        .order_by(models.EmailVerificationCode.id.desc()),
    )


def send_verification_email(email: str, code: str) -> None:
    settings = get_settings()
    subject = "Verify your StudentSpend account"
    body = (
        f"Your StudentSpend verification code is {code}.\n\n"
        f"It expires in {settings.email_verification_minutes} minutes."
    )

    if not settings.smtp_host:
        logger.info("SMTP not configured - verification code for %s: %s (development mode)", email, code)
        print(f"[StudentSpend] Verification code for {email}: {code}")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_email
    message["To"] = email
    message.set_content(body)

    smtp_class = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
    try:
        logger.debug("Sending verification email to %s via %s:%d", email, settings.smtp_host, settings.smtp_port)
        with smtp_class(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout) as smtp:
            if settings.smtp_use_tls and not settings.smtp_use_ssl:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        logger.info("Verification email sent successfully to %s", email)
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("Failed to send verification email to %s: %s", email, str(exc))
        raise EmailDeliveryError("Verification email could not be sent") from exc
