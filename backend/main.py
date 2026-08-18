from datetime import UTC, datetime, date as date_type, timedelta
from decimal import Decimal
from pathlib import Path
import sys
import time
import json
import csv
import io
import hashlib
import uuid
import urllib.request
import shutil
import subprocess
import threading
import secrets

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from redis.exceptions import RedisError
from fastapi.responses import FileResponse
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import (
    authenticate_user,
    check_login_rate_limit,
    clear_failed_logins,
    create_access_token,
    create_password_reset_token,
    decode_password_reset_token,
    get_current_user,
    hash_password,
    normalize_email,
    record_failed_login,
    create_refresh_token,
    create_two_factor_token,
    decode_two_factor_token,
    verify_refresh_token,
    verify_password,
    revoke_refresh_token,
    revoke_all_user_tokens,
    check_api_rate_limit,
    invalidate_state_cache,
    require_role,
    get_redis,
)
from backend.config import get_settings
from backend.database import Base, engine, get_db, SessionLocal
from backend.email_verification import (
    EmailDeliveryError,
    create_verification_code,
    send_email_with_attachment,
    send_plain_email,
    send_password_reset_email,
    send_verification_email,
    hash_verification_code,
    latest_pending_code,
)
from backend.logging_config import setup_logging, get_logger, get_security_logger, get_access_logger
from backend.metrics import metrics_response, observe_job, observe_request
from backend.seed import seed_user_defaults
from backend.two_factor import generate_totp_secret, provisioning_uri, verify_totp

# Setup logging
setup_logging()

app = FastAPI(title="StudentSpend API")
app.add_middleware(GZipMiddleware, minimum_size=500)
settings = get_settings()
FRONTEND_DIR = Path(__file__).resolve().parent.parent
logger = get_logger(__name__)
security_logger = get_security_logger()
access_logger = get_access_logger()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware to log all HTTP requests and responses."""
    start_time = time.time()
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    correlation_id = request.headers.get("X-Correlation-ID") or request_id
    api_version = settings.api_version
    
    request.state.client_ip = request.client.host if request.client else "unknown"
    request.state.request_id = request_id
    request.state.correlation_id = correlation_id
    request.state.api_version = api_version
    
    access_logger.info(
        "request_started",
        extra={
            "event": "request_started",
            "request_id": request_id,
            "correlation_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.state.client_ip,
            "api_version": api_version,
        },
    )
    
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        observe_request(request.method, request.url.path, response.status_code, duration)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-API-Version"] = api_version
        
        access_logger.info(
            "request_completed",
            extra={
                "event": "request_completed",
                "request_id": request_id,
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
                "client_ip": request.state.client_ip,
                "api_version": api_version,
            },
        )
        
        return response
    except Exception as e:
        duration = time.time() - start_time
        observe_request(request.method, request.url.path, 500, duration)
        # Handle specific SQLAlchemy errors globally
        if "UniqueViolation" in str(e) or "duplicate key" in str(e).lower():
            response = Response(
                content=json.dumps({"detail": "This record already exists."}),
                status_code=409,
                media_type="application/json"
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id
            response.headers["X-API-Version"] = api_version
            return response
            
        logger.error(
            "request_failed",
            exc_info=True,
            extra={
                "event": "request_failed",
                "request_id": request_id,
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round(duration * 1000, 2),
                "client_ip": request.state.client_ip,
                "api_version": api_version,
            },
        )
        raise


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-API-Version"] = settings.api_version
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self' http://127.0.0.1:8003; "
        "font-src 'self';"
    )
    return response


@app.on_event("startup")
def startup() -> None:
    logger.info("Starting StudentSpend API server...")
    Base.metadata.create_all(bind=engine)
    ensure_user_profile_columns()
    ensure_user_role_column()
    ensure_user_range_columns()
    ensure_security_columns()
    ensure_two_factor_columns()
    ensure_expense_archive_columns()
    ensure_expense_receipt_columns()
    ensure_expense_tax_columns()
    ensure_settings_dark_mode_column()
    ensure_refresh_token_device_columns()
    ensure_database_indexes()
    reset_legacy_starter_budgets()
    reset_legacy_starter_goals()
    seed_default_feature_flags()
    seed_default_tax_categories()
    start_maintenance_threads()
    logger.info("StudentSpend API server started successfully")


@app.get("/health", response_model=schemas.HealthRead)
def health(request: Request) -> dict[str, str | None]:
    log_health_event(request, "health_check", "ok")
    return health_payload(request, "ok")


@app.get("/health/db", response_model=schemas.DependencyHealthRead)
def health_db(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    start_time = time.time()
    try:
        db.execute(text("SELECT 1"))
        latency_ms = round((time.time() - start_time) * 1000, 2)
        log_health_event(request, "health_db_check", "ok", latency_ms=latency_ms)
        return {**health_payload(request, "ok"), "dependency": "database", "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        log_health_event(request, "health_db_check", "error", latency_ms=latency_ms, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database health check failed")


@app.get("/health/redis", response_model=schemas.DependencyHealthRead)
def health_redis(request: Request, redis = Depends(get_redis)) -> dict[str, object]:
    start_time = time.time()
    if redis is None:
        log_health_event(request, "health_redis_check", "error", detail="redis client unavailable")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis client unavailable")
    try:
        redis.ping()
        latency_ms = round((time.time() - start_time) * 1000, 2)
        log_health_event(request, "health_redis_check", "ok", latency_ms=latency_ms)
        return {**health_payload(request, "ok"), "dependency": "redis", "latency_ms": latency_ms}
    except RedisError as exc:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        log_health_event(request, "health_redis_check", "error", latency_ms=latency_ms, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis health check failed")


@app.get("/api/version")
@app.get("/api/v1/version")
def api_version() -> dict[str, str]:
    return {"api_version": settings.api_version}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    content, media_type = metrics_response()
    return Response(content=content, media_type=media_type)


@app.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "public, max-age=60"},
    )


@app.get("/{asset_name}", include_in_schema=False)
def frontend_asset(asset_name: str) -> FileResponse:
    allowed_assets = {"app.js", "styles.css"}
    if asset_name not in allowed_assets:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return FileResponse(
        FRONTEND_DIR / asset_name,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.post("/api/auth/signup", response_model=schemas.TokenRead, status_code=status.HTTP_201_CREATED)
def signup(payload: schemas.SignupRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict[str, object]:
    email = normalize_email(payload.email)
    logger.info("Signup attempt for email=%s", email)
    
    existing_user = db.scalar(select(models.User).where(models.User.email == email))
    if existing_user is not None:
        logger.warning("Signup failed: email already registered: email=%s", email)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    is_first_user = db.scalar(select(func.count(models.User.id))) == 0
    user = models.User(
        name=f"{payload.first_name.strip()} {payload.last_name.strip()}",
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        gender=payload.gender,
        email=email,
        password_hash=hash_password(payload.password),
        role="admin" if is_first_user else "student",
        email_verified=is_first_user,
    )
    db.add(user)
    db.flush()
    seed_user_defaults(db, user)
    create_notification(
        db,
        user.id,
        "account",
        "Welcome to StudentSpend",
        "Your account was created successfully.",
    )
    db.commit()
    db.refresh(user)
    background_send_verification(db, user, background_tasks)

    logger.info("User signup successful: user_id=%s, email=%s, auto_verified=%s", user.id, email, is_first_user)
    security_logger.info("New user registered: user_id=%s, email=%s", user.id, email)
    return {"access_token": create_access_token(user), "profile": user}


@app.post("/api/auth/login", response_model=schemas.AuthResponse)
def login(payload: schemas.LoginRequest, request: Request, response: Response, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict[str, object]:
    email = normalize_email(payload.email)
    client_ip = getattr(request.state, "client_ip", "unknown")
    logger.debug("Login attempt for email=%s, ip=%s", email, client_ip)
    
    check_login_rate_limit(payload.email)
    existing_user = db.scalar(select(models.User).where(models.User.email == email))
    if existing_user is not None and is_account_locked(existing_user):
        security_logger.warning(
            "Account login blocked by lockout: user_id=%s, email=%s, ip=%s",
            existing_user.id,
            email,
            client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account locked until {as_aware_utc(existing_user.locked_until).isoformat()}",
        )

    user = authenticate_user(db, payload.email, payload.password)
    if user is None:
        record_failed_login(payload.email)
        if existing_user is not None:
            record_persistent_failed_login(db, existing_user, request)
        security_logger.warning("Failed login attempt: email=%s, ip=%s", email, client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    clear_failed_logins(payload.email)
    clear_persistent_failed_logins(db, user)

    if user.two_factor_enabled:
        security_logger.info("2FA challenge required: user_id=%s, email=%s, ip=%s", user.id, email, client_ip)
        return {
            "requires_two_factor": True,
            "two_factor_token": create_two_factor_token(user),
            "token_type": "bearer",
        }
    
    # Trigger background maintenance
    background_tasks.add_task(cleanup_expired_data)
    background_tasks.add_task(process_recurring_expenses, user.id)
    
    logger.info("Login successful: user_id=%s, email=%s, ip=%s", user.id, email, client_ip)
    token = create_access_token(user)
    # create refresh token and set as cookie
    try:
        device = upsert_user_device(db, user, request)
        plaintext, rt = create_refresh_token(db, user, device.id)
        create_notification(
            db,
            user.id,
            "security",
            "New sign-in",
            f"New sign-in from {device.ip_address or 'unknown IP'}.",
        )
        db.commit()
        # response might be a FastAPI Response object; try to set cookie if available
        # set cookie name 'refresh_token' at path /api/auth/refresh so it's scoped
        if isinstance(response, Response):
            response.set_cookie(
                key="refresh_token",
                value=plaintext,
                httponly=True,
                secure=get_settings().cookie_secure,
                samesite="strict",
                path="/api/auth/refresh",
                max_age=get_settings().refresh_token_days * 24 * 3600,
            )
    except Exception:
        logger.exception("Failed to create refresh token")

    return {"access_token": token, "profile": user}


@app.post("/api/auth/2fa/verify", response_model=schemas.TokenRead)
def verify_two_factor_login(
    payload: schemas.TwoFactorVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user_id = decode_two_factor_token(payload.two_factor_token)
    user = db.get(models.User, user_id)
    if user is None or not user.two_factor_enabled or not user.two_factor_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid two-factor challenge")
    if not verify_totp(user.two_factor_secret, payload.code):
        security_logger.warning(
            "Invalid 2FA code: user_id=%s, ip=%s",
            user.id,
            getattr(request.state, "client_ip", "unknown"),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid two-factor code")

    token = create_access_token(user)
    try:
        device = upsert_user_device(db, user, request)
        plaintext, rt = create_refresh_token(db, user, device.id)
        create_notification(
            db,
            user.id,
            "security",
            "New verified sign-in",
            f"Two-factor sign-in from {device.ip_address or 'unknown IP'}.",
        )
        db.commit()
        response.set_cookie(
            key="refresh_token",
            value=plaintext,
            httponly=True,
            secure=get_settings().cookie_secure,
            samesite="strict",
            path="/api/auth/refresh",
            max_age=get_settings().refresh_token_days * 24 * 3600,
        )
    except Exception:
        logger.exception("Failed to create refresh token after 2FA")

    return {"access_token": token, "profile": user}


@app.post("/api/auth/2fa/setup", response_model=schemas.TwoFactorSetupRead)
def setup_two_factor(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    require_verified_email(user)
    if user.two_factor_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Two-factor authentication is already enabled")
    secret = user.two_factor_secret or generate_totp_secret()
    user.two_factor_secret = secret
    db.commit()
    return {"secret": secret, "otpauth_uri": provisioning_uri(secret, user.email)}


@app.post("/api/auth/2fa/enable", response_model=schemas.ProfileRead)
def enable_two_factor(
    payload: schemas.TwoFactorEnableRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.User:
    require_verified_email(user)
    if not user.two_factor_secret:
        user.two_factor_secret = generate_totp_secret()
    if not verify_totp(user.two_factor_secret, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid two-factor code")
    user.two_factor_enabled = True
    create_notification(db, user.id, "security", "Two-factor authentication enabled", "Your account now requires a one-time code at sign-in.")
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/auth/2fa/disable", response_model=schemas.ProfileRead)
def disable_two_factor(
    payload: schemas.TwoFactorDisableRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.User:
    require_verified_email(user)
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    if user.two_factor_secret and not verify_totp(user.two_factor_secret, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid two-factor code")
    user.two_factor_enabled = False
    user.two_factor_secret = None
    create_notification(db, user.id, "security", "Two-factor authentication disabled", "Your account no longer requires a one-time code at sign-in.")
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/auth/verify-email", response_model=schemas.TokenRead)
def verify_email(payload: schemas.VerifyEmailRequest, response: Response, db: Session = Depends(get_db)) -> dict[str, object]:
    user = db.scalar(select(models.User).where(models.User.email == normalize_email(payload.email)))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if user.email_verified:
        return {"access_token": create_access_token(user), "profile": user}

    verification_code = latest_pending_code(db, user)
    if verification_code is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")
    if as_aware_utc(verification_code.expires_at) < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")
    if verification_code.attempts >= settings.email_verification_max_attempts:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many verification attempts")

    verification_code.attempts += 1
    if verification_code.code_hash != hash_verification_code(user.email, payload.code):
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")

    verification_code.used_at = datetime.now(UTC)
    user.email_verified = True
    db.commit()
    db.refresh(user)
    token = create_access_token(user)
    try:
        plaintext, rt = create_refresh_token(db, user)
        if isinstance(response, Response):
            response.set_cookie(
                key="refresh_token",
                value=plaintext,
                httponly=True,
                secure=get_settings().cookie_secure,
                samesite="strict",
                path="/api/auth/refresh",
                max_age=get_settings().refresh_token_days * 24 * 3600,
            )
    except Exception:
        logger.exception("Failed to create refresh token on verify")

    return {"access_token": token, "profile": user}


@app.post("/api/auth/resend-verification", response_model=schemas.MessageRead)
def resend_verification(payload: schemas.ResendVerificationRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.scalar(select(models.User).where(models.User.email == normalize_email(payload.email)))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if user.email_verified:
        return {"message": "Email is already verified"}

    background_send_verification(db, user, background_tasks)
    return {"message": "Verification code sent"}


@app.post("/api/auth/refresh", response_model=schemas.TokenRead)
def refresh_token(response: Response, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    # Read refresh token from cookie
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    rt = verify_refresh_token(db, token)
    if not rt:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = db.get(models.User, rt.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    rt.last_used_at = datetime.now(UTC)
    if rt.device is not None:
        rt.device.last_seen_at = datetime.now(UTC)
        rt.device.ip_address = getattr(request.state, "client_ip", rt.device.ip_address)
        rt.device.user_agent = request.headers.get("user-agent", rt.device.user_agent)
    db.commit()

    # rotate: revoke current and issue a new one
    try:
        revoke_refresh_token(db, rt)
        plaintext, new_rt = create_refresh_token(db, user, rt.device_id)
        response.set_cookie(
            key="refresh_token",
            value=plaintext,
            httponly=True,
            secure=get_settings().cookie_secure,
            samesite="strict",
            path="/api/auth/refresh",
            max_age=get_settings().refresh_token_days * 24 * 3600,
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not rotate refresh token")

    return {"access_token": create_access_token(user), "profile": user}


@app.post("/api/auth/logout", response_model=schemas.MessageRead)
def logout(response: Response, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)) -> dict[str, str]:
    # Revoke all refresh tokens for the user and clear cookie
    revoke_all_user_tokens(db, user)
    response.delete_cookie("refresh_token", path="/api/auth/refresh")
    return {"message": "Logged out"}


@app.get("/api/sessions", response_model=list[schemas.SessionRead])
@app.get("/api/v1/sessions", response_model=list[schemas.SessionRead])
def list_sessions(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[dict[str, object]]:
    require_verified_email(user)
    tokens = db.scalars(
        select(models.RefreshToken)
        .where(models.RefreshToken.user_id == user.id)
        .order_by(models.RefreshToken.created_at.desc())
    ).all()
    return [session_payload(token) for token in tokens]


@app.delete("/api/sessions/{session_id}", response_model=schemas.MessageRead)
@app.delete("/api/v1/sessions/{session_id}", response_model=schemas.MessageRead)
def revoke_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    token = db.scalar(
        select(models.RefreshToken).where(
            models.RefreshToken.id == session_id,
            models.RefreshToken.user_id == user.id,
        )
    )
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    token.revoked = True
    db.commit()
    return {"message": "Session revoked"}


@app.get("/api/devices", response_model=list[schemas.DeviceRead])
@app.get("/api/v1/devices", response_model=list[schemas.DeviceRead])
def list_devices(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.UserDevice]:
    require_verified_email(user)
    return db.scalars(
        select(models.UserDevice)
        .where(models.UserDevice.user_id == user.id)
        .order_by(models.UserDevice.last_seen_at.desc())
    ).all()


@app.post("/api/auth/forgot-password", response_model=schemas.MessageRead)
def forgot_password(
    payload: schemas.ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    email = normalize_email(payload.email)
    user = db.scalar(select(models.User).where(models.User.email == email))

    if user is not None:
        token = create_password_reset_token(user)
        background_tasks.add_task(
            send_password_reset_email,
            user.email,
            token,
            user.first_name or user.name,
        )

    # Always return the same message regardless of whether the email exists
    # This prevents email enumeration attacks
    return {"message": "If an account exists with this email, password reset instructions will be sent."}


@app.post("/api/auth/reset-password", response_model=schemas.MessageRead)
def reset_password(
    payload: schemas.PasswordResetRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        user_id = decode_password_reset_token(payload.token)
    except HTTPException:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset link")

    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset link")

    user.password_hash = hash_password(payload.new_password)
    revoke_all_user_tokens(db, user)
    db.commit()
    logger.info("Password reset completed: user_id=%s", user.id)
    security_logger.info("Password reset completed: user_id=%s", user.id)
    return {"message": "Password updated. You can now sign in with your new password."}


@app.get("/api/state", response_model=schemas.AppStateRead)
def read_state(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
    redis = Depends(get_redis),
) -> dict[str, object]:
    require_verified_email(user)
    check_api_rate_limit(user.id)
    
    # Try to fetch from cache first
    cache_key = f"state:{user.id}"
    if redis:
        try:
            cached_data = redis.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
        except RedisError as e:
            logger.error("Redis cache read error: %s", e)

    categories = db.scalars(select(models.Category).where(models.Category.user_id == user.id).order_by(models.Category.id)).all()
    expenses = db.scalars(select(models.Expense).where(models.Expense.user_id == user.id).order_by(models.Expense.date.desc(), models.Expense.id.desc())).all()
    goal = db.scalars(select(models.Goal).where(models.Goal.user_id == user.id).order_by(models.Goal.id)).first()
    if goal is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Savings goal was not initialized")

    settings = db.scalars(select(models.UserSettings).where(models.UserSettings.user_id == user.id)).first()
    if settings is None:
        settings = {"country": "United States", "savings_currencies": []}

    state = {"profile": user, "categories": categories, "expenses": expenses, "goal": goal, "settings": settings}
    
    # Store in cache for 5 minutes (300 seconds)
    if redis:
        try:
            redis.setex(cache_key, 300, json.dumps(jsonable_encoder(state)))
        except RedisError as e:
            logger.error("Redis cache write error: %s", e)

    return state


@app.patch("/api/settings", response_model=schemas.UserSettingsRead)
def update_settings(
    payload: schemas.SettingsUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.UserSettings:
    require_verified_email(user)
    settings = db.scalars(select(models.UserSettings).where(models.UserSettings.user_id == user.id)).first()
    if settings is None:
        settings = models.UserSettings(user_id=user.id, country=payload.country or "United States", savings_currencies=payload.savings_currencies or [])
        db.add(settings)
    else:
        if payload.country is not None:
            settings.country = payload.country
        if payload.savings_currencies is not None:
            settings.savings_currencies = payload.savings_currencies

    db.commit()
    db.refresh(settings)
    invalidate_state_cache(user.id)
    return settings


@app.get("/api/notifications", response_model=list[schemas.NotificationRead])
@app.get("/api/v1/notifications", response_model=list[schemas.NotificationRead])
def list_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.Notification]:
    require_verified_email(user)
    query = select(models.Notification).where(models.Notification.user_id == user.id)
    if unread_only:
        query = query.where(models.Notification.read == False)
    return db.scalars(query.order_by(models.Notification.created_at.desc()).limit(100)).all()


@app.patch("/api/notifications/{notification_id}/read", response_model=schemas.NotificationRead)
@app.patch("/api/v1/notifications/{notification_id}/read", response_model=schemas.NotificationRead)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.Notification:
    notification = db.scalar(
        select(models.Notification).where(
            models.Notification.id == notification_id,
            models.Notification.user_id == user.id,
        )
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.read = True
    notification.read_at = datetime.now(UTC)
    db.commit()
    db.refresh(notification)
    return notification


@app.patch("/api/notifications/read-all", response_model=schemas.MessageRead)
@app.patch("/api/v1/notifications/read-all", response_model=schemas.MessageRead)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    db.query(models.Notification).filter(
        models.Notification.user_id == user.id,
        models.Notification.read == False,
    ).update({"read": True, "read_at": datetime.now(UTC)})
    db.commit()
    return {"message": "Notifications marked as read"}


@app.patch("/api/profile", response_model=schemas.ProfileRead)
def update_profile(
    payload: schemas.ProfileUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.User:
    require_verified_email(user)
    user.allowance = payload.allowance
    if payload.preferred_range is not None:
        user.preferred_range = payload.preferred_range
    if payload.custom_range_start is not None:
        user.custom_range_start = payload.custom_range_start
    if payload.custom_range_end is not None:
        user.custom_range_end = payload.custom_range_end
    db.commit()
    db.refresh(user)
    logger.info("Profile updated for user_id=%s: allowance=%s, preferred_range=%s", 
                user.id, user.allowance, user.preferred_range)
    invalidate_state_cache(user.id)
    return user


@app.post("/api/expenses", response_model=schemas.ExpenseRead, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: schemas.ExpenseCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.Expense:
    require_verified_email(user)
    logger.debug("Creating expense for user_id=%s: name=%s, amount=%s, category=%s", 
                 user.id, payload.name, payload.amount, payload.category)
    expense = models.Expense(user_id=user.id, **payload.model_dump())
    db.add(expense)
    db.commit()
    db.refresh(expense)
    alert_category = db.scalar(
        select(models.Category)
        .where(models.Category.user_id == user.id, models.Category.name == payload.category)
    )
    if alert_category and alert_category.budget and alert_category.budget > 0:
        category_spent = db.scalar(
            select(func.coalesce(func.sum(models.Expense.amount), 0))
            .where(
                models.Expense.user_id == user.id,
                models.Expense.category == payload.category,
                models.Expense.deleted == False,
            )
        )
        if category_spent is None:
            category_spent = 0
        threshold = Decimal("0.9") * alert_category.budget
        previous_spent = category_spent - Decimal(str(payload.amount))
        if previous_spent < threshold <= category_spent:
            create_notification(
                db,
                user.id,
                "budget",
                "Budget limit warning",
                f"{alert_category.name} has reached {float(category_spent / alert_category.budget * 100):.0f}% of its budget.",
            )
            background_tasks.add_task(
                send_budget_limit_email,
                user.email,
                user.first_name or user.name,
                alert_category.name,
                float(category_spent / alert_category.budget * 100),
                float(alert_category.budget),
            )
            db.commit()
    logger.info("Expense created: expense_id=%s, user_id=%s, name=%s, amount=%s", 
                expense.id, user.id, payload.name, payload.amount)
    invalidate_state_cache(user.id)
    return expense


def send_budget_limit_email(email: str, recipient_name: str, category: str, percent: float, budget: float) -> None:
    subject = f"Budget alert: {category} is nearing your limit"
    body = (
        f"Hi {recipient_name},\n\n"
        f"You have used {percent:.0f}% of your budget for {category}.\n"
        f"Current budget: {budget:.2f}\n\n"
        "If you want, adjust your category limit or review spending to stay on track.\n\n"
        "Thanks,\n"
        "The StudentSpend team"
    )
    send_plain_email(email, subject, body)


@app.patch("/api/categories/{category_id}", response_model=schemas.CategoryRead)
def update_category(
    category_id: int,
    payload: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.Category:
    require_verified_email(user)
    category = db.scalar(
        select(models.Category).where(
            models.Category.id == category_id,
            models.Category.user_id == user.id,
        ),
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    category.budget = payload.budget
    db.commit()
    db.refresh(category)
    invalidate_state_cache(user.id)
    return category


@app.patch("/api/expenses/{expense_id}/delete", response_model=schemas.ExpenseRead)
def soft_delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.Expense:
    require_verified_email(user)
    expense = db.scalar(
        select(models.Expense).where(models.Expense.id == expense_id, models.Expense.user_id == user.id)
    )
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if expense.deleted:
        return expense

    expense.deleted = True
    expense.deleted_at = datetime.now(UTC)
    db.commit()
    db.refresh(expense)
    logger.info("Expense soft-deleted: expense_id=%s, user_id=%s", expense.id, user.id)
    invalidate_state_cache(user.id)
    return expense


@app.patch("/api/expenses/{expense_id}", response_model=schemas.ExpenseRead)
def update_expense(
    expense_id: int,
    payload: schemas.ExpenseUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.Expense:
    require_verified_email(user)
    expense = db.scalar(
        select(models.Expense).where(models.Expense.id == expense_id, models.Expense.user_id == user.id)
    )
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if expense.deleted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expense is in the recycle bin and cannot be edited")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(expense, field, value)

    db.commit()
    db.refresh(expense)
    logger.info("Expense updated: expense_id=%s, user_id=%s", expense.id, user.id)
    invalidate_state_cache(user.id)
    return expense


@app.post("/api/expenses/{expense_id}/restore", response_model=schemas.ExpenseRead)
def restore_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.Expense:
    require_verified_email(user)
    expense = db.scalar(
        select(models.Expense).where(models.Expense.id == expense_id, models.Expense.user_id == user.id)
    )
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if not expense.deleted:
        return expense

    expense.deleted = False
    expense.deleted_at = None
    db.commit()
    db.refresh(expense)
    logger.info("Expense restored: expense_id=%s, user_id=%s", expense.id, user.id)
    invalidate_state_cache(user.id)
    return expense


@app.get("/api/expenses/recycle", response_model=schemas.ExpenseListRead)
def list_recycle_bin(
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    category: str = "",
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, object]:
    require_verified_email(user)
    page = max(1, page)
    per_page = min(max(1, per_page), 100)

    filters = [models.Expense.user_id == user.id, models.Expense.deleted == True]

    if search:
        search_pattern = f"%{search.lower()}%"
        filters.append(models.Expense.name.ilike(search_pattern))
    if category:
        filters.append(models.Expense.category == category)
    if start_date:
        filters.append(models.Expense.date >= start_date)
    if end_date:
        filters.append(models.Expense.date <= end_date)

    query = select(models.Expense).where(*filters).order_by(models.Expense.deleted_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    expenses = db.scalars(query.limit(per_page).offset((page - 1) * per_page)).all()
    total_pages = (int(total or 0) + per_page - 1) // per_page if total else 1
    pagination = schemas.PaginationInfo(
        page=page,
        per_page=per_page,
        total=int(total or 0),
        total_pages=total_pages,
        has_next=(page < total_pages),
        has_prev=(page > 1),
    )
    return {"expenses": expenses, "pagination": pagination}


@app.delete("/api/expenses/{expense_id}", response_model=schemas.MessageRead)
def permanently_delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    require_verified_email(user)
    expense = db.scalar(
        select(models.Expense).where(models.Expense.id == expense_id, models.Expense.user_id == user.id)
    )
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")

    if not expense.deleted:
        # To prevent accidental hard deletes, require that expense be soft-deleted first
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expense must be in recycle bin before permanent deletion")

    db.delete(expense)
    db.commit()
    logger.info("Expense permanently deleted: expense_id=%s, user_id=%s", expense_id, user.id)
    invalidate_state_cache(user.id)
    return {"message": "Expense permanently deleted"}


@app.get("/api/expenses", response_model=schemas.ExpenseListRead)
def list_expenses(
    page: int = 1,
    per_page: int = 20,
    search: str = "",
    category: str = "",
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    min_amount: float = 0,
    max_amount: float = 0,
    include_deleted: bool = False,
    include_archived: bool = False,
    sort_by: str = Query("date", pattern="^(date|amount|category|name)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, object]:
    require_verified_email(user)

    # Validate pagination
    page = max(1, page)
    per_page = min(max(1, per_page), 100)

    # Build query
    filters = [models.Expense.user_id == user.id]
    if not include_deleted:
        filters.append(models.Expense.deleted == False)
    if not include_archived:
        filters.append(models.Expense.archived == False)

    query = select(models.Expense).where(*filters)

    # Apply search filter
    if search:
        search_pattern = f"%{search.lower()}%"
        query = query.where(models.Expense.name.ilike(search_pattern))

    # Apply category filter
    if category:
        query = query.where(models.Expense.category == category)

    # Apply date range filters
    if start_date:
        query = query.where(models.Expense.date >= start_date)
    if end_date:
        query = query.where(models.Expense.date <= end_date)

    # Apply amount range filters
    if min_amount > 0:
        query = query.where(models.Expense.amount >= min_amount)
    if max_amount > 0:
        query = query.where(models.Expense.amount <= max_amount)

    # Get total count before pagination
    count_query = select(models.Expense.id).where(*filters)
    if search:
        count_query = count_query.where(models.Expense.name.ilike(search_pattern))
    if category:
        count_query = count_query.where(models.Expense.category == category)
    if start_date:
        count_query = count_query.where(models.Expense.date >= start_date)
    if end_date:
        count_query = count_query.where(models.Expense.date <= end_date)
    if min_amount > 0:
        count_query = count_query.where(models.Expense.amount >= min_amount)
    if max_amount > 0:
        count_query = count_query.where(models.Expense.amount <= max_amount)

    total = db.scalar(select(func.count()).select_from(count_query.subquery()))

    # Order and paginate
    sort_columns = {
        "date": models.Expense.date,
        "amount": models.Expense.amount,
        "category": models.Expense.category,
        "name": models.Expense.name,
    }
    sort_column = sort_columns[sort_by]
    query = query.order_by(sort_column.asc() if sort_dir == "asc" else sort_column.desc(), models.Expense.id.desc())
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    expenses = db.scalars(query).all()

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return {
        "expenses": expenses,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }


@app.get("/api/search/expenses", response_model=schemas.ExpenseListRead)
def search_expenses(
    page: int = 1,
    per_page: int = 20,
    q: str = "",
    categories: list[str] = Query(default=[]),
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, object]:
    require_verified_email(user)
    page = max(1, page)
    per_page = min(max(1, per_page), 100)

    conditions = [
        models.Expense.user_id == user.id,
        models.Expense.deleted == False,
    ]
    if not include_archived:
        conditions.append(models.Expense.archived == False)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            models.Expense.name.ilike(pattern) | models.Expense.category.ilike(pattern)
        )
    if categories:
        conditions.append(models.Expense.category.in_(categories))
    if start_date:
        conditions.append(models.Expense.date >= start_date)
    if end_date:
        conditions.append(models.Expense.date <= end_date)
    if min_amount is not None:
        conditions.append(models.Expense.amount >= min_amount)
    if max_amount is not None:
        conditions.append(models.Expense.amount <= max_amount)

    base_query = select(models.Expense).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
    expenses = db.scalars(
        base_query.order_by(models.Expense.date.desc(), models.Expense.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    total_pages = (int(total) + per_page - 1) // per_page or 1
    return {
        "expenses": expenses,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": int(total),
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }


@app.put("/api/goal", response_model=schemas.GoalRead)
def update_goal(
    payload: schemas.GoalUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.Goal:
    require_verified_email(user)
    goal = db.scalars(select(models.Goal).where(models.Goal.user_id == user.id).order_by(models.Goal.id)).first()
    if goal is None:
        goal = models.Goal(user_id=user.id, **payload.model_dump())
        db.add(goal)
    else:
        goal.name = payload.name
        goal.target = payload.target
        goal.saved = payload.saved

    db.commit()
    db.refresh(goal)
    invalidate_state_cache(user.id)
    return goal


def require_verified_email(user: models.User) -> None:
    if not user.email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email verification required")


def health_payload(request: Request, status_value: str) -> dict[str, str | None]:
    return {
        "status": status_value,
        "api_version": settings.api_version,
        "request_id": getattr(request.state, "request_id", None),
        "correlation_id": getattr(request.state, "correlation_id", None),
    }


def log_health_event(
    request: Request,
    event: str,
    status_value: str,
    latency_ms: float | None = None,
    detail: str | None = None,
) -> None:
    payload = {
        "event": event,
        "request_id": getattr(request.state, "request_id", None),
        "correlation_id": getattr(request.state, "correlation_id", None),
        "method": request.method,
        "path": request.url.path,
        "status_code": 200 if status_value == "ok" else 503,
        "client_ip": getattr(request.state, "client_ip", None),
        "api_version": settings.api_version,
    }
    if latency_ms is not None:
        payload["duration_ms"] = latency_ms
    if detail:
        payload["detail"] = detail
    access_logger.info(event, extra=payload)


def is_account_locked(user: models.User) -> bool:
    locked_until = getattr(user, "locked_until", None)
    return locked_until is not None and as_aware_utc(locked_until) > datetime.now(UTC)


def record_persistent_failed_login(db: Session, user: models.User, request: Request) -> None:
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= settings.login_max_attempts:
        user.locked_until = datetime.now(UTC) + timedelta_minutes(settings.login_lockout_minutes)
        create_notification(
            db,
            user.id,
            "security",
            "Account locked",
            f"Your account was locked after {settings.login_max_attempts} failed login attempts.",
        )
        security_logger.warning(
            "Account locked: user_id=%s, email=%s, ip=%s, lockout_minutes=%d",
            user.id,
            user.email,
            getattr(request.state, "client_ip", "unknown"),
            settings.login_lockout_minutes,
        )
    db.commit()


def clear_persistent_failed_logins(db: Session, user: models.User) -> None:
    if (user.failed_login_attempts or 0) == 0 and user.locked_until is None:
        return
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()


def timedelta_minutes(minutes: int):
    from datetime import timedelta

    return timedelta(minutes=minutes)


def upsert_user_device(db: Session, user: models.User, request: Request) -> models.UserDevice:
    now = datetime.now(UTC)
    user_agent = request.headers.get("user-agent", "")
    ip_address = getattr(request.state, "client_ip", "unknown")
    fingerprint = hashlib.sha256(f"{user.id}:{user_agent}:{ip_address}".encode("utf-8")).hexdigest()
    device = db.scalar(
        select(models.UserDevice).where(
            models.UserDevice.user_id == user.id,
            models.UserDevice.device_fingerprint == fingerprint,
        )
    )
    if device is None:
        device = models.UserDevice(
            user_id=user.id,
            device_fingerprint=fingerprint,
            user_agent=user_agent,
            ip_address=ip_address,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(device)
        db.flush()
    else:
        device.user_agent = user_agent
        device.ip_address = ip_address
        device.last_seen_at = now
    return device


def create_notification(db: Session, user_id: int, type_: str, title: str, message: str) -> models.Notification:
    notification = models.Notification(
        user_id=user_id,
        type=type_,
        title=title,
        message=message,
        read=False,
        created_at=datetime.now(UTC),
    )
    db.add(notification)
    return notification


def session_payload(token: models.RefreshToken) -> dict[str, object]:
    device = token.device
    return {
        "id": token.id,
        "jti": token.jti,
        "created_at": token.created_at,
        "expires_at": token.expires_at,
        "last_used_at": token.last_used_at,
        "revoked": token.revoked,
        "device_id": token.device_id,
        "user_agent": device.user_agent if device else None,
        "ip_address": device.ip_address if device else None,
    }


def background_send_verification(db: Session, user: models.User, background_tasks: BackgroundTasks) -> None:
    code = create_verification_code(db, user)
    background_tasks.add_task(send_verification_email, user.email, code)
    logger.info("Verification email queued for background task: email=%s", user.email)


def generate_expense_csv(expenses: list[models.Expense]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Category", "Name", "Amount"])

    for exp in expenses:
        writer.writerow([exp.date.isoformat(), exp.category, exp.name, str(exp.amount)])

    return output.getvalue().encode("utf-8")


def resolve_country_currency(country: str) -> str:
    mapping = {
        "united states": "USD",
        "united kingdom": "GBP",
        "uk": "GBP",
        "canada": "CAD",
        "eurozone": "EUR",
        "france": "EUR",
        "germany": "EUR",
        "spain": "EUR",
        "italy": "EUR",
        "india": "INR",
        "australia": "AUD",
        "japan": "JPY",
    }
    return mapping.get(country.strip().lower(), "USD")

@app.get("/api/expenses/export")
def export_expenses(
    format: str = Query("csv", pattern="^(csv)$"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    """Export user expenses to CSV."""
    require_verified_email(user)
    check_api_rate_limit(user.id)
    
    expenses = db.scalars(
        select(models.Expense)
        .where(models.Expense.user_id == user.id, models.Expense.deleted == False)
        .order_by(models.Expense.date.desc())
    ).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Category", "Name", "Amount"])
    
    for exp in expenses:
        writer.writerow([exp.date, exp.category, exp.name, exp.amount])
    
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=expenses_{datetime.now().strftime('%Y%m%d')}.csv"}
    )


@app.post("/api/expenses/export/email", response_model=schemas.MessageRead)
def email_expense_statement(
    payload: schemas.ExpenseExportEmailRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    check_api_rate_limit(user.id)

    destination = payload.email or user.email
    expenses = db.scalars(
        select(models.Expense)
        .where(models.Expense.user_id == user.id, models.Expense.deleted == False)
        .order_by(models.Expense.date.desc())
    ).all()

    if payload.format != "csv":
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Only csv export is supported currently")

    csv_bytes = generate_expense_csv(expenses)
    filename = f"student_expenses_{datetime.now().strftime('%Y%m%d')}.csv"
    subject = "Your StudentSpend expense statement"
    body = (
        f"Hello {user.first_name or user.name},\n\n"
        "Attached is your latest expense statement from StudentSpend.\n\n"
        "Thank you for using StudentSpend!\n"
    )

    try:
        send_email_with_attachment(
            email=destination,
            subject=subject,
            body=body,
            attachment_bytes=csv_bytes,
            filename=filename,
            mime_type="text/csv",
        )
    except EmailDeliveryError as exc:
        logger.error("Statement email failed for user_id=%s: %s", user.id, str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not send statement email")

    return {"message": f"Statement emailed to {destination}"}

@app.get("/api/analytics/categories", response_model=list[schemas.CategoryAnalytics])
def get_category_analytics(
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    """Get spending breakdown by category."""
    require_verified_email(user)
    check_api_rate_limit(user.id)
    
    query = select(
        models.Expense.category,
        func.sum(models.Expense.amount).label("total_amount"),
        func.count(models.Expense.id).label("transaction_count")
    ).where(models.Expense.user_id == user.id, models.Expense.deleted == False)
    
    if start_date:
        query = query.where(models.Expense.date >= start_date)
    if end_date:
        query = query.where(models.Expense.date <= end_date)
        
    query = query.group_by(models.Expense.category)
    results = db.execute(query).all()
    
    return [{"category": r[0], "total_amount": r[1], "transaction_count": r[2]} for r in results]


@app.get("/api/admin/dashboard", response_model=schemas.AdminDashboardRead)
def get_admin_dashboard(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_role(user, "admin")
    check_api_rate_limit(user.id)

    total_users = db.scalar(select(func.count(models.User.id))) or 0
    verified_users = db.scalar(select(func.count(models.User.id)).where(models.User.email_verified == True)) or 0
    total_expenses = db.scalar(select(func.count(models.Expense.id)).where(models.Expense.deleted == False)) or 0
    total_spend = db.scalar(select(func.coalesce(func.sum(models.Expense.amount), 0)).where(models.Expense.deleted == False)) or Decimal("0")

    category_query = (
        select(
            models.Expense.category,
            func.sum(models.Expense.amount).label("total_amount"),
            func.count(models.Expense.id).label("transaction_count")
        )
        .where(models.Expense.deleted == False)
        .group_by(models.Expense.category)
        .order_by(func.sum(models.Expense.amount).desc())
        .limit(5)
    )
    category_results = db.execute(category_query).all()

    top_categories = [
        {"category": r[0], "total_amount": r[1], "transaction_count": r[2]}
        for r in category_results
    ]

    return {
        "total_users": total_users,
        "verified_users": verified_users,
        "total_expenses": total_expenses,
        "total_spend": total_spend,
        "top_categories": top_categories,
    }


@app.post("/api/admin/backups", response_model=schemas.BackupRead, status_code=status.HTTP_201_CREATED)
def create_backup_endpoint(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.BackupRecord:
    require_role(user, "admin")
    return create_database_backup(db, initiated_by_user_id=user.id)


@app.get("/api/admin/backups", response_model=list[schemas.BackupRead])
def list_backups(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.BackupRecord]:
    require_role(user, "admin")
    return db.scalars(select(models.BackupRecord).order_by(models.BackupRecord.started_at.desc()).limit(50)).all()


@app.post("/api/reports/schedules", response_model=schemas.ScheduledReportRead, status_code=status.HTTP_201_CREATED)
def create_report_schedule(
    payload: schemas.ScheduledReportCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.ScheduledReport:
    require_verified_email(user)
    report = models.ScheduledReport(
        user_id=user.id,
        email=payload.email or user.email,
        frequency=payload.frequency,
        format=payload.format,
        active=True,
        next_run_at=next_report_run(payload.frequency),
        created_at=datetime.now(UTC),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@app.get("/api/reports/schedules", response_model=list[schemas.ScheduledReportRead])
def list_report_schedules(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.ScheduledReport]:
    require_verified_email(user)
    return db.scalars(
        select(models.ScheduledReport)
        .where(models.ScheduledReport.user_id == user.id)
        .order_by(models.ScheduledReport.created_at.desc())
    ).all()


@app.patch("/api/reports/schedules/{report_id}/toggle", response_model=schemas.ScheduledReportRead)
def toggle_report_schedule(
    report_id: int,
    active: bool,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.ScheduledReport:
    require_verified_email(user)
    report = db.scalar(
        select(models.ScheduledReport).where(
            models.ScheduledReport.id == report_id,
            models.ScheduledReport.user_id == user.id,
        )
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report schedule not found")
    report.active = active
    if active and as_aware_utc(report.next_run_at) < datetime.now(UTC):
        report.next_run_at = next_report_run(report.frequency)
    db.commit()
    db.refresh(report)
    return report


@app.get("/api/admin/feature-flags", response_model=list[schemas.FeatureFlagRead])
def list_feature_flags(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.FeatureFlag]:
    require_role(user, "admin")
    return db.scalars(select(models.FeatureFlag).order_by(models.FeatureFlag.key)).all()


@app.put("/api/admin/feature-flags/{flag_key}", response_model=schemas.FeatureFlagRead)
def upsert_feature_flag(
    flag_key: str,
    payload: schemas.FeatureFlagUpsert,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.FeatureFlag:
    require_role(user, "admin")
    now = datetime.now(UTC)
    flag = db.scalar(select(models.FeatureFlag).where(models.FeatureFlag.key == flag_key))
    if flag is None:
        flag = models.FeatureFlag(key=flag_key, created_at=now, updated_at=now)
        db.add(flag)
    flag.description = payload.description
    flag.enabled = payload.enabled
    flag.audience = payload.audience
    flag.updated_at = now
    db.commit()
    db.refresh(flag)
    return flag


@app.get("/api/feature-flags")
def read_enabled_feature_flags(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, bool]:
    flags = db.scalars(select(models.FeatureFlag)).all()
    return {flag.key: is_feature_enabled(flag, user) for flag in flags}


@app.post("/api/admin/queue/jobs", response_model=schemas.QueueJobRead, status_code=status.HTTP_201_CREATED)
def enqueue_job_endpoint(
    payload: schemas.QueueJobCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.QueueJob:
    require_role(user, "admin")
    job = enqueue_job(db, payload.task_name, payload.payload, payload.scheduled_for)
    db.commit()
    db.refresh(job)
    return job


@app.get("/api/admin/queue/jobs", response_model=list[schemas.QueueJobRead])
def list_queue_jobs(
    status_filter: str = "",
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.QueueJob]:
    require_role(user, "admin")
    query = select(models.QueueJob)
    if status_filter:
        query = query.where(models.QueueJob.status == status_filter)
    return db.scalars(query.order_by(models.QueueJob.scheduled_for.desc()).limit(100)).all()


@app.post("/api/admin/queue/run", response_model=schemas.MessageRead)
def run_queue_once_endpoint(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    require_role(user, "admin")
    processed = process_queue_jobs(db)
    return {"message": f"Processed {processed} queued jobs"}


@app.post("/api/expenses/archive", response_model=schemas.ArchiveRead)
def archive_expenses_endpoint(
    payload: schemas.ArchiveRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.ArchiveRecord:
    require_verified_email(user)
    record = archive_user_expenses(db, user.id, payload.archived_before)
    db.commit()
    db.refresh(record)
    invalidate_state_cache(user.id)
    return record


@app.get("/api/expenses/archives", response_model=list[schemas.ArchiveRead])
def list_archives(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.ArchiveRecord]:
    require_verified_email(user)
    return db.scalars(
        select(models.ArchiveRecord)
        .where(models.ArchiveRecord.user_id == user.id)
        .order_by(models.ArchiveRecord.created_at.desc())
    ).all()

@app.get("/api/analytics/total-balance", response_model=schemas.TotalBalanceRead)
def get_total_converted_balance(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
    redis = Depends(get_redis)
):
    """Calculate total balance across all wallets converted to home currency."""
    require_verified_email(user)
    settings = db.scalar(select(models.UserSettings).where(models.UserSettings.user_id == user.id))
    if not settings or not settings.savings_currencies:
        return {"home_currency": "USD", "total_converted_balance": 0}

    home_curr = resolve_country_currency(settings.country)
    # For brevity, let's assume home currency is based on country.
    # Usually you'd have a mapping.
    
    rates = get_exchange_rates(redis)
    if not rates:
        raise HTTPException(status_code=503, detail="Exchange rate service unavailable")

    total = Decimal("0")
    base_rate = Decimal(str(rates.get("USD", 1))) # API usually returns base USD
    
    for wallet in settings.savings_currencies:
        curr = wallet.get("currency", "USD")
        amount = Decimal(str(wallet.get("amount", 0)))
        
        # Convert to USD then to home currency
        rate_to_usd = Decimal(str(rates.get(curr, 1)))
        rate_home = Decimal(str(rates.get(home_curr, 1)))
        
        amount_usd = amount / rate_to_usd
        total += amount_usd * rate_home

    return {"home_currency": home_curr, "total_converted_balance": total.quantize(Decimal("0.01"))}

@app.post("/api/recurring-expenses", response_model=schemas.RecurringExpenseRead)
def create_recurring_expense(
    payload: schemas.RecurringExpenseCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    require_verified_email(user)
    recurring = models.RecurringExpense(user_id=user.id, **payload.model_dump())
    db.add(recurring)
    db.commit()
    db.refresh(recurring)
    return recurring


@app.get("/api/recurring-expenses", response_model=list[schemas.RecurringExpenseRead])
def list_recurring_expenses(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    check_api_rate_limit(user.id)
    return db.scalars(
        select(models.RecurringExpense).where(models.RecurringExpense.user_id == user.id).order_by(models.RecurringExpense.name)
    ).all()


@app.patch("/api/recurring-expenses/{recurring_id}", response_model=schemas.RecurringExpenseRead)
def update_recurring_expense(
    recurring_id: int,
    payload: schemas.RecurringExpenseUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    recurring = db.scalar(
        select(models.RecurringExpense)
        .where(models.RecurringExpense.id == recurring_id, models.RecurringExpense.user_id == user.id)
    )
    if recurring is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recurring expense not found")

    if payload.name is not None:
        recurring.name = payload.name
    if payload.amount is not None:
        recurring.amount = payload.amount
    if payload.category is not None:
        recurring.category = payload.category
    if payload.frequency is not None:
        recurring.frequency = payload.frequency
    if payload.day_of_month is not None:
        recurring.day_of_month = payload.day_of_month
    if payload.day_of_week is not None:
        recurring.day_of_week = payload.day_of_week

    db.commit()
    db.refresh(recurring)
    invalidate_state_cache(user.id)
    return recurring


@app.delete("/api/recurring-expenses/{recurring_id}", response_model=schemas.MessageRead)
def delete_recurring_expense(
    recurring_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    recurring = db.scalar(
        select(models.RecurringExpense)
        .where(models.RecurringExpense.id == recurring_id, models.RecurringExpense.user_id == user.id)
    )
    if recurring is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recurring expense not found")

    db.delete(recurring)
    db.commit()
    invalidate_state_cache(user.id)
    return {"message": "Recurring expense removed"}

def get_exchange_rates(redis) -> dict:
    """Fetch exchange rates with Redis caching (24h TTL)."""
    cache_key = "exchange_rates:v1"
    if redis:
        try:
            cached = redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except RedisError as e:
            logger.error("Redis cache read error in get_exchange_rates: %s", e)

    try:
        url = f"{get_settings().exchange_rate_api_url}USD"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            rates = data.get("rates", {})
            if redis and rates:
                try:
                    redis.setex(cache_key, 86400, json.dumps(rates))
                except RedisError as e:
                    logger.error("Redis cache write error in get_exchange_rates: %s", e)
            return rates
    except Exception as e:
        logger.error("Failed to fetch exchange rates: %s", e)
        return {}

def process_recurring_expenses(user_id: int) -> None:
    """Background task to generate expenses from recurring templates."""
    db = SessionLocal()
    try:
        today = datetime.now(UTC).date()
        recurring_list = db.scalars(
            select(models.RecurringExpense).where(models.RecurringExpense.user_id == user_id)
        ).all()

        for item in recurring_list:
            should_generate = False
            
            # Basic monthly logic: day of month matches and not yet done this month
            if item.frequency == "monthly":
                if today.day >= (item.day_of_month or 1):
                    if not item.last_generated_at or (item.last_generated_at.month != today.month or item.last_generated_at.year != today.year):
                        should_generate = True

            elif item.frequency == "yearly":
                if today.day == (item.day_of_month or 1):
                    if not item.last_generated_at or item.last_generated_at.year != today.year:
                        should_generate = True
            
            # Basic weekly logic: day of week matches and not yet done this week
            elif item.frequency == "weekly":
                if today.weekday() == (item.day_of_week or 0):
                    if not item.last_generated_at or (today - item.last_generated_at).days >= 7:
                        should_generate = True

            if should_generate:
                new_expense = models.Expense(
                    user_id=user_id,
                    name=item.name,
                    amount=item.amount,
                    category=item.category,
                    date=today
                )
                item.last_generated_at = today
                db.add(new_expense)
                logger.info("Generated recurring expense for user_id=%s: %s", user_id, item.name)
        
        db.commit()
        invalidate_state_cache(user_id)
    except Exception as e:
        logger.error("Error processing recurring expenses: %s", e)
    finally:
        db.close()

def cleanup_expired_data() -> None:
    """
    Background task to remove expired entries from the database.
    Uses a fresh session to ensure thread safety outside the request lifecycle.
    """
    db = SessionLocal()
    try:
        now = datetime.now(UTC)
        # Purge expired refresh tokens
        db.query(models.RefreshToken).filter(models.RefreshToken.expires_at < now).delete()
        # Purge expired email verification codes
        db.query(models.EmailVerificationCode).filter(models.EmailVerificationCode.expires_at < now).delete()
        # Purge soft-deleted expenses older than recycle_bin_ttl_days
        ttl_days = get_settings().recycle_bin_ttl_days
        cutoff = now - timedelta(days=ttl_days)
        deleted_count = db.query(models.Expense).filter(
            models.Expense.deleted == True,
            models.Expense.deleted_at < cutoff,
        ).delete()
        if deleted_count:
            logger.info("Purged %d permanently deleted expenses older than %d days", deleted_count, ttl_days)
        db.commit()
        logger.info("Background cleanup: expired tokens and codes purged.")
    except Exception as e:
        logger.error("Background cleanup failed: %s", str(e))
    finally:
        db.close()


def create_database_backup(db: Session, initiated_by_user_id: int | None = None) -> models.BackupRecord:
    now = datetime.now(UTC)
    backup_dir = Path(get_settings().backup_dir)
    if not backup_dir.is_absolute():
        backup_dir = FRONTEND_DIR / backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    filename = f"studentspend_backup_{now.strftime('%Y%m%d_%H%M%S')}.dump"
    destination = backup_dir / filename
    record = models.BackupRecord(
        filename=str(destination),
        status="running",
        started_at=now,
        size_bytes=0,
        detail="",
        initiated_by_user_id=initiated_by_user_id,
    )
    db.add(record)
    db.flush()

    try:
        url = engine.url
        if url.drivername.startswith("sqlite"):
            source = url.database
            if not source:
                raise RuntimeError("SQLite database path is unavailable")
            destination = destination.with_suffix(".sqlite3")
            shutil.copy2(source, destination)
            record.filename = str(destination)
        elif url.drivername.startswith("postgresql"):
            pg_dump_path = get_settings().backup_pg_dump_path
            if Path(pg_dump_path).is_absolute():
                resolved_pg_dump = Path(pg_dump_path)
                if not resolved_pg_dump.exists():
                    raise RuntimeError(f"pg_dump path not found: {pg_dump_path}")
                resolved_pg_dump = str(resolved_pg_dump)
            else:
                resolved_pg_dump = shutil.which(pg_dump_path)
                if not resolved_pg_dump:
                    raise RuntimeError(
                        "PostgreSQL backup requires pg_dump to be installed and available on PATH. "
                        "Set BACKUP_PG_DUMP_PATH if pg_dump is not on PATH."
                    )
            command = [resolved_pg_dump, str(url), "-Fc", "-f", str(destination)]
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
        elif url.drivername.startswith("mysql"):
            dump_tool = shutil.which("mariadb-dump") or shutil.which("mysqldump")
            if not dump_tool:
                raise RuntimeError(
                    "MySQL/MariaDB backup requires mariadb-dump or mysqldump on PATH."
                )
            destination = destination.with_suffix(".sql")
            record.filename = str(destination)
            command = [
                dump_tool,
                f"--user={url.username or 'root'}",
                f"--password={url.password or ''}",
                "--host=localhost",
                "--single-transaction",
                "--routines",
                "--triggers",
                url.database,
            ]
            with open(destination, "w") as f:
                subprocess.run(command, check=True, stdout=f, stderr=subprocess.PIPE, text=True, timeout=120)
        else:
            raise RuntimeError(f"Unsupported database driver for backup: {url.drivername}")

        record.status = "completed"
        record.completed_at = datetime.now(UTC)
        record.size_bytes = destination.stat().st_size
        record.detail = "Backup completed"
    except Exception as exc:
        record.status = "failed"
        record.completed_at = datetime.now(UTC)
        record.detail = str(exc)
        logger.error("Database backup failed: %s", exc)

    db.commit()
    db.refresh(record)
    return record


def should_create_automatic_backup(db: Session) -> bool:
    if not get_settings().backup_enabled:
        return False
    latest = db.scalar(
        select(models.BackupRecord)
        .where(models.BackupRecord.status == "completed")
        .order_by(models.BackupRecord.completed_at.desc())
    )
    if latest is None or latest.completed_at is None:
        return True
    return as_aware_utc(latest.completed_at) <= datetime.now(UTC) - timedelta(hours=get_settings().backup_interval_hours)


def next_report_run(frequency: str, from_time: datetime | None = None) -> datetime:
    base = from_time or datetime.now(UTC)
    if frequency == "daily":
        return base + timedelta(days=1)
    if frequency == "monthly":
        return base + timedelta(days=30)
    return base + timedelta(days=7)


def send_scheduled_reports(db: Session) -> int:
    now = datetime.now(UTC)
    reports = db.scalars(
        select(models.ScheduledReport)
        .where(models.ScheduledReport.active == True, models.ScheduledReport.next_run_at <= now)
        .limit(20)
    ).all()
    sent = 0
    for report in reports:
        expenses = db.scalars(
            select(models.Expense)
            .where(
                models.Expense.user_id == report.user_id,
                models.Expense.deleted == False,
                models.Expense.archived == False,
            )
            .order_by(models.Expense.date.desc())
        ).all()
        csv_bytes = generate_expense_csv(expenses)
        try:
            send_email_with_attachment(
                email=report.email,
                subject="Your scheduled StudentSpend report",
                body="Attached is your scheduled StudentSpend expense report.\n",
                attachment_bytes=csv_bytes,
                filename=f"scheduled_expenses_{now.strftime('%Y%m%d')}.csv",
                mime_type="text/csv",
            )
            report.last_run_at = now
            report.next_run_at = next_report_run(report.frequency, now)
            sent += 1
        except EmailDeliveryError as exc:
            logger.error("Scheduled report failed: report_id=%s, error=%s", report.id, exc)
            report.next_run_at = now + timedelta(hours=1)
    db.commit()
    return sent


def enqueue_job(db: Session, task_name: str, payload: dict[str, object] | None = None, scheduled_for: datetime | None = None) -> models.QueueJob:
    job = models.QueueJob(
        task_name=task_name,
        payload=payload or {},
        status="queued",
        scheduled_for=scheduled_for or datetime.now(UTC),
    )
    db.add(job)
    db.flush()
    return job


def process_queue_jobs(db: Session, limit: int = 10) -> int:
    now = datetime.now(UTC)
    jobs = db.scalars(
        select(models.QueueJob)
        .where(models.QueueJob.status == "queued", models.QueueJob.scheduled_for <= now)
        .order_by(models.QueueJob.scheduled_for.asc(), models.QueueJob.id.asc())
        .limit(limit)
    ).all()
    processed = 0
    for job in jobs:
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.attempts += 1
        db.commit()
        try:
            execute_queue_job(db, job)
            job.status = "completed"
            job.finished_at = datetime.now(UTC)
            job.error = ""
            observe_job(job.task_name, "completed")
        except Exception as exc:
            job.error = str(exc)
            job.status = "failed" if job.attempts >= job.max_attempts else "queued"
            job.scheduled_for = datetime.now(UTC) + timedelta(minutes=5)
            observe_job(job.task_name, "failed")
            logger.error("Queue job failed: job_id=%s task=%s error=%s", job.id, job.task_name, exc)
        processed += 1
        db.commit()
    return processed


def execute_queue_job(db: Session, job: models.QueueJob) -> None:
    if job.task_name == "cleanup_expired_data":
        cleanup_expired_data()
    elif job.task_name == "database_backup":
        create_database_backup(db)
    elif job.task_name == "scheduled_reports":
        send_scheduled_reports(db)
    elif job.task_name == "archive_old_expenses":
        cutoff = datetime.now(UTC).date() - timedelta(days=get_settings().archive_after_days)
        archive_all_users_expenses(db, cutoff)
    else:
        raise ValueError(f"Unknown task: {job.task_name}")


def archive_user_expenses(db: Session, user_id: int, archived_before: date_type, record_zero: bool = True) -> models.ArchiveRecord | None:
    now = datetime.now(UTC)
    count = db.query(models.Expense).filter(
        models.Expense.user_id == user_id,
        models.Expense.deleted == False,
        models.Expense.archived == False,
        models.Expense.date < archived_before,
    ).update({"archived": True, "archived_at": now}, synchronize_session=False)
    if not count and not record_zero:
        return None
    record = models.ArchiveRecord(
        user_id=user_id,
        archived_before=archived_before,
        archived_count=int(count or 0),
        status="completed",
        created_at=now,
    )
    db.add(record)
    return record


def archive_all_users_expenses(db: Session, archived_before: date_type) -> int:
    user_ids = db.scalars(select(models.User.id)).all()
    total = 0
    for user_id in user_ids:
        record = archive_user_expenses(db, user_id, archived_before, record_zero=False)
        if record is not None:
            total += record.archived_count
            invalidate_state_cache(user_id)
    db.commit()
    return total


def is_feature_enabled(flag: models.FeatureFlag, user: models.User) -> bool:
    if not flag.enabled:
        return False
    audience = flag.audience or {}
    roles = audience.get("roles")
    if isinstance(roles, list) and roles and user.role not in roles:
        return False
    user_ids = audience.get("user_ids")
    if isinstance(user_ids, list) and user_ids and user.id not in user_ids:
        return False
    return True


_maintenance_started = False


def start_maintenance_threads() -> None:
    global _maintenance_started
    if _maintenance_started:
        return
    _maintenance_started = True
    thread = threading.Thread(target=maintenance_loop, name="studentspend-maintenance", daemon=True)
    thread.start()


def maintenance_loop() -> None:
    while True:
        try:
            with Session(engine) as db:
                if should_create_automatic_backup(db):
                    url = engine.url
                    if url.drivername.startswith("postgresql"):
                        pg_dump_path = get_settings().backup_pg_dump_path
                        if not shutil.which(pg_dump_path) and not Path(pg_dump_path).is_absolute():
                            logger.warning(
                                "Automatic PostgreSQL backup skipped: pg_dump is not installed or not available on PATH."
                            )
                        else:
                            create_database_backup(db)
                    else:
                        create_database_backup(db)
                send_scheduled_reports(db)
                process_queue_jobs(db)
                cutoff = datetime.now(UTC).date() - timedelta(days=get_settings().archive_after_days)
                archive_all_users_expenses(db, cutoff)
        except Exception:
            logger.exception("Maintenance loop failed")
        time.sleep(max(60, get_settings().maintenance_interval_seconds))


def reset_legacy_starter_goals() -> None:
    with Session(engine) as db:
        goals = db.scalars(
            select(models.Goal)
            .join(models.User)
            .where(
                models.Goal.name == "Emergency fund",
                models.Goal.target == 600,
                models.Goal.saved == 225,
                ~select(models.Expense.id).where(models.Expense.user_id == models.Goal.user_id).exists(),
            ),
        ).all()
        for goal in goals:
            goal.saved = 0
        if goals:
            db.commit()


def ensure_user_profile_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    profile_columns = {
        "first_name": "VARCHAR(80) NOT NULL DEFAULT ''",
        "last_name": "VARCHAR(80) NOT NULL DEFAULT ''",
        "gender": "VARCHAR(32) NOT NULL DEFAULT ''",
    }

    with engine.begin() as connection:
        for column_name, column_definition in profile_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}"))


def ensure_user_role_column() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" in existing_columns:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'student'"))


def ensure_user_range_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    range_columns = {
        "preferred_range": "VARCHAR(20) NOT NULL DEFAULT 'week'",
        "custom_range_start": "DATE NULL",
        "custom_range_end": "DATE NULL",
    }

    with engine.begin() as connection:
        for column_name, column_definition in range_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}"))


def ensure_security_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    security_columns = {
        "failed_login_attempts": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "TIMESTAMP NULL",
    }

    with engine.begin() as connection:
        for column_name, column_definition in security_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}"))


def ensure_two_factor_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    two_factor_columns = {
        "two_factor_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
        "two_factor_secret": "VARCHAR(64) NULL",
    }

    with engine.begin() as connection:
        for column_name, column_definition in two_factor_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}"))


def ensure_expense_archive_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("expenses"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("expenses")}
    archive_columns = {
        "archived": "BOOLEAN NOT NULL DEFAULT FALSE",
        "archived_at": "TIMESTAMP NULL",
    }

    with engine.begin() as connection:
        for column_name, column_definition in archive_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE expenses ADD COLUMN {column_name} {column_definition}"))


def ensure_refresh_token_device_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("refresh_tokens"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("refresh_tokens")}
    with engine.begin() as connection:
        if "device_id" not in existing_columns:
            connection.execute(text("ALTER TABLE refresh_tokens ADD COLUMN device_id INTEGER NULL"))


def ensure_database_indexes() -> None:
    index_statements = [
        "CREATE INDEX IF NOT EXISTS ix_expenses_user_deleted_date_id ON expenses (user_id, deleted, date, id)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_user_category_date ON expenses (user_id, category, date)",
        "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_revoked_expires ON refresh_tokens (user_id, revoked, expires_at)",
        "CREATE INDEX IF NOT EXISTS ix_user_devices_user_last_seen ON user_devices (user_id, last_seen_at)",
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created ON notifications (user_id, `read`, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_scheduled_reports_active_next_run ON scheduled_reports (active, next_run_at)",
        "CREATE INDEX IF NOT EXISTS ix_queue_jobs_status_scheduled ON queue_jobs (status, scheduled_for)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_user_archived_date ON expenses (user_id, archived, date)",
    ]
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for statement in index_statements:
            table_name = statement.split(" ON ", 1)[1].split(" ", 1)[0]
            if table_name in tables:
                connection.execute(text(statement))


def seed_default_feature_flags() -> None:
    defaults = {
        "two_factor_authentication": "Require a TOTP code during login when enabled by a user.",
        "scheduled_reports": "Allow users to receive recurring expense reports.",
        "expense_archiving": "Hide old expenses from default lists while retaining them.",
        "queue_workers": "Enable durable background job processing.",
    }
    now = datetime.now(UTC)
    with Session(engine) as db:
        changed = False
        for key, description in defaults.items():
            existing = db.scalar(select(models.FeatureFlag).where(models.FeatureFlag.key == key))
            if existing is None:
                db.add(
                    models.FeatureFlag(
                        key=key,
                        description=description,
                        enabled=True,
                        audience={},
                        created_at=now,
                        updated_at=now,
                    )
                )
                changed = True
        if changed:
            db.commit()


def reset_legacy_starter_budgets() -> None:
    starter_budgets = {
        "Food": 260,
        "Transport": 120,
        "Books": 150,
        "Rent": 420,
        "Social": 100,
        "Health": 80,
    }
    with Session(engine) as db:
        users_without_expenses = select(models.User.id).where(
            ~select(models.Expense.id).where(models.Expense.user_id == models.User.id).exists(),
        )
        categories = db.scalars(
            select(models.Category).where(
                models.Category.user_id.in_(users_without_expenses),
                models.Category.name.in_(starter_budgets),
            ),
        ).all()
        changed = False
        for category in categories:
            if category.budget == starter_budgets[category.name]:
                category.budget = 0
                changed = True
        if changed:
            db.commit()


def as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def ensure_expense_receipt_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("expenses"):
        return
    existing_columns = {column["name"] for column in inspector.get_columns("expenses")}
    with engine.begin() as connection:
        if "receipt_path" not in existing_columns:
            connection.execute(text("ALTER TABLE expenses ADD COLUMN receipt_path VARCHAR(500) NULL"))


def ensure_expense_tax_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("expenses"):
        return
    existing_columns = {column["name"] for column in inspector.get_columns("expenses")}
    with engine.begin() as connection:
        if "tax_deductible" not in existing_columns:
            connection.execute(text("ALTER TABLE expenses ADD COLUMN tax_deductible BOOLEAN NOT NULL DEFAULT FALSE"))
        if "tax_category" not in existing_columns:
            connection.execute(text("ALTER TABLE expenses ADD COLUMN tax_category VARCHAR(80) NULL"))


def ensure_settings_dark_mode_column() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("user_settings"):
        return
    existing_columns = {column["name"] for column in inspector.get_columns("user_settings")}
    with engine.begin() as connection:
        if "dark_mode" not in existing_columns:
            connection.execute(text("ALTER TABLE user_settings ADD COLUMN dark_mode BOOLEAN NOT NULL DEFAULT FALSE"))


def seed_default_tax_categories() -> None:
    pass


# ──────────────────────────────────────────────────────────────
# Feature 1: CSV Import
# ──────────────────────────────────────────────────────────────

@app.post("/api/expenses/import", response_model=schemas.CSVImportResponse)
def import_expenses_csv(
    payload: schemas.CSVImportRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, object]:
    require_verified_email(user)
    imported = 0
    skipped = 0
    errors: list[str] = []
    for i, row in enumerate(payload.rows):
        try:
            from datetime import date as date_type
            exp_date = date_type.fromisoformat(row.date)
            expense = models.Expense(
                user_id=user.id,
                name=row.name,
                amount=Decimal(str(row.amount)),
                category=row.category,
                date=exp_date,
            )
            db.add(expense)
            imported += 1
        except Exception as e:
            skipped += 1
            errors.append(f"Row {i+1}: {str(e)}")
    db.commit()
    invalidate_state_cache(user.id)
    return {"imported": imported, "skipped": skipped, "errors": errors}


# ──────────────────────────────────────────────────────────────
# Feature 2: Receipt Photo Storage
# ──────────────────────────────────────────────────────────────

import base64
import os

RECEIPTS_DIR = FRONTEND_DIR / "receipts"
RECEIPTS_DIR.mkdir(exist_ok=True)


@app.post("/api/expenses/{expense_id}/receipt")
async def upload_receipt(
    expense_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    require_verified_email(user)
    expense = db.scalar(
        select(models.Expense).where(models.Expense.id == expense_id, models.Expense.user_id == user.id)
    )
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    body = await request.json()
    image_data = body.get("image")
    if not image_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No image data provided")

    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    filename = f"receipt_{user.id}_{expense_id}_{int(datetime.now(UTC).timestamp())}.jpg"
    filepath = RECEIPTS_DIR / filename
    filepath.write_bytes(base64.b64decode(image_data))

    expense.receipt_path = filename
    db.commit()
    return {"expense_id": expense_id, "receipt_url": f"/receipts/{filename}"}


@app.get("/api/expenses/{expense_id}/receipt")
def get_receipt(
    expense_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    expense = db.scalar(
        select(models.Expense).where(models.Expense.id == expense_id, models.Expense.user_id == user.id)
    )
    if expense is None or not expense.receipt_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    filepath = RECEIPTS_DIR / expense.receipt_path
    if not filepath.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt file not found")
    import mimetypes
    mime = mimetypes.guess_type(str(filepath))[0] or "image/jpeg"
    return FileResponse(filepath, media_type=mime)


# ──────────────────────────────────────────────────────────────
# Feature 4: Budget Forecasting
# ──────────────────────────────────────────────────────────────

@app.get("/api/analytics/forecast", response_model=schemas.BudgetForecastRead)
def get_budget_forecast(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    today = datetime.now(UTC).date()
    days_in_month = (today.replace(month=today.month % 12 + 1, day=1) - timedelta(days=1)).day if today.month < 12 else 31
    days_elapsed = today.day

    expenses = db.scalars(
        select(models.Expense).where(
            models.Expense.user_id == user.id,
            models.Expense.deleted == False,
            models.Expense.date >= today.replace(day=1),
        )
    ).all()

    total_spent = sum(float(e.amount) for e in expenses)
    daily_rate = Decimal(str(total_spent / max(days_elapsed, 1)))
    projected_total = daily_rate * days_in_month

    categories = db.scalars(
        select(models.Category).where(models.Category.user_id == user.id)
    ).all()
    budget_map = {c.name: float(c.budget) for c in categories if c.budget > 0}

    category_totals: dict[str, float] = {}
    for e in expenses:
        category_totals[e.category] = category_totals.get(e.category, 0) + float(e.amount)

    category_forecasts = []
    for cat_name, spent in category_totals.items():
        cat_budget = budget_map.get(cat_name, 0)
        cat_daily = spent / max(days_elapsed, 1)
        cat_projected = cat_daily * days_in_month
        category_forecasts.append({
            "category": cat_name,
            "spent": spent,
            "projected": round(cat_projected, 2),
            "budget": cat_budget,
            "over_budget": cat_projected > cat_budget if cat_budget > 0 else False,
        })

    allowance = float(user.allowance or 0)
    on_track = projected_total <= allowance

    return {
        "projected_total": projected_total.quantize(Decimal("0.01")),
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "daily_rate": daily_rate.quantize(Decimal("0.01")),
        "on_track": on_track,
        "category_forecasts": category_forecasts,
    }


# ──────────────────────────────────────────────────────────────
# Feature 5: Recurring Expense Auto-Detection
# ──────────────────────────────────────────────────────────────

@app.get("/api/analytics/recurring-suggestions", response_model=list[schemas.RecurringSuggestion])
def get_recurring_suggestions(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    six_months_ago = datetime.now(UTC).date() - timedelta(days=180)
    expenses = db.scalars(
        select(models.Expense).where(
            models.Expense.user_id == user.id,
            models.Expense.deleted == False,
            models.Expense.date >= six_months_ago,
        ).order_by(models.Expense.date)
    ).all()

    from collections import defaultdict
    name_dates: dict[str, list[date_type]] = defaultdict(list)
    name_amounts: dict[str, list[float]] = defaultdict(list)
    name_categories: dict[str, str] = {}

    for e in expenses:
        name_dates[e.name.lower().strip()].append(e.date)
        name_amounts[e.name.lower().strip()].append(float(e.amount))
        name_categories[e.name.lower().strip()] = e.category

    existing = set(
        r.name.lower() for r in db.scalars(
            select(models.RecurringExpense).where(models.RecurringExpense.user_id == user.id)
        ).all()
    )

    suggestions = []
    for name, dates in name_dates.items():
        if name in existing or len(dates) < 3:
            continue

        amounts = name_amounts[name]
        avg_amount = sum(amounts) / len(amounts)
        all_same = all(abs(a - avg_amount) / avg_amount < 0.15 for a in amounts if avg_amount > 0)

        if not all_same:
            continue

        gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        avg_gap = sum(gaps) / len(gaps) if gaps else 30

        if 5 <= avg_gap <= 10:
            freq = "weekly"
        elif 25 <= avg_gap <= 35:
            freq = "monthly"
        elif 350 <= avg_gap <= 380:
            freq = "yearly"
        else:
            continue

        confidence = min(1.0, len(dates) / 6)
        suggestions.append({
            "name": name.title(),
            "amount": round(avg_amount, 2),
            "category": name_categories.get(name, "Other"),
            "frequency": freq,
            "confidence": round(confidence, 2),
            "occurrences": len(dates),
        })

    return sorted(suggestions, key=lambda s: s["confidence"], reverse=True)[:10]


# ──────────────────────────────────────────────────────────────
# Feature 6: Spending Insights / AI Coach
# ──────────────────────────────────────────────────────────────

@app.get("/api/analytics/insights", response_model=list[schemas.SpendingInsight])
def get_spending_insights(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    today = datetime.now(UTC).date()
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)

    this_week = db.scalars(
        select(models.Expense).where(
            models.Expense.user_id == user.id,
            models.Expense.deleted == False,
            models.Expense.date >= this_week_start,
        )
    ).all()

    last_week = db.scalars(
        select(models.Expense).where(
            models.Expense.user_id == user.id,
            models.Expense.deleted == False,
            models.Expense.date >= last_week_start,
            models.Expense.date < this_week_start,
        )
    ).all()

    insights: list[dict] = []
    this_total = sum(float(e.amount) for e in this_week)
    last_total = sum(float(e.amount) for e in last_week)

    if last_total > 0:
        change_pct = ((this_total - last_total) / last_total) * 100
        if change_pct > 20:
            insights.append({
                "type": "spending_increase",
                "title": "Spending trending up",
                "message": f"You've spent {change_pct:.0f}% more this week (${this_total:.2f}) vs last week (${last_total:.2f}).",
                "severity": "warning",
            })
        elif change_pct < -20:
            insights.append({
                "type": "spending_decrease",
                "title": "Great spending discipline",
                "message": f"You've spent {abs(change_pct):.0f}% less this week. Keep it up!",
                "severity": "success",
            })

    allowance = float(user.allowance or 0)
    if allowance > 0:
        monthly_spent = sum(
            float(e.amount) for e in db.scalars(
                select(models.Expense).where(
                    models.Expense.user_id == user.id,
                    models.Expense.deleted == False,
                    models.Expense.date >= today.replace(day=1),
                )
            ).all()
        )
        remaining_days = (today.replace(month=today.month % 12 + 1, day=1) - timedelta(days=1)).day - today.day
        daily_budget_left = (allowance - monthly_spent) / max(remaining_days, 1)
        if daily_budget_left < 0:
            insights.append({
                "type": "over_budget",
                "title": "Over budget alert",
                "message": f"You've exceeded your allowance by ${abs(monthly_spent - allowance):.2f}. Consider cutting back.",
                "severity": "error",
            })
        elif daily_budget_left < allowance / 30 * 0.5:
            insights.append({
                "type": "tight_budget",
                "title": "Budget running low",
                "message": f"You have ${allowance - monthly_spent:.2f} left for {remaining_days} days (${daily_budget_left:.2f}/day).",
                "severity": "warning",
            })

    from collections import Counter
    cat_counts = Counter(e.category for e in this_week)
    if cat_counts:
        top_cat, top_count = cat_counts.most_common(1)[0]
        if top_count >= 3:
            insights.append({
                "type": "category_pattern",
                "title": f"Heavy {top_cat} spending",
                "message": f"You've made {top_count} {top_cat} purchases this week. Consider setting a budget for this category.",
                "severity": "info",
            })

    all_this_month = db.scalars(
        select(models.Expense).where(
            models.Expense.user_id == user.id,
            models.Expense.deleted == False,
            models.Expense.date >= today.replace(day=1),
        )
    ).all()

    if all_this_month:
        avg_expense = sum(float(e.amount) for e in all_this_month) / len(all_this_month)
        big_expenses = [e for e in all_this_month if float(e.amount) > avg_expense * 3]
        if big_expenses:
            insights.append({
                "type": "large_expense",
                "title": "Unusual large expenses",
                "message": f"You have {len(big_expenses)} expenses significantly above your average (${avg_expense:.2f}).",
                "severity": "info",
            })

    if not insights:
        insights.append({
            "type": "on_track",
            "title": "Looking good",
            "message": "Your spending is consistent and on track. Keep monitoring!",
            "severity": "success",
        })

    return insights


# ──────────────────────────────────────────────────────────────
# Feature 7: Savings Challenges
# ──────────────────────────────────────────────────────────────

@app.post("/api/savings-challenges", response_model=schemas.SavingsChallenge, status_code=status.HTTP_201_CREATED)
def create_savings_challenge(
    payload: schemas.SavingsChallengeCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.SavingsChallenge:
    require_verified_email(user)
    challenge = models.SavingsChallenge(
        user_id=user.id,
        name=payload.name,
        target_amount=payload.target_amount,
        current_amount=0,
        start_date=payload.start_date,
        end_date=payload.end_date,
        created_at=datetime.now(UTC),
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge


@app.get("/api/savings-challenges", response_model=list[schemas.SavingsChallenge])
def list_savings_challenges(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.SavingsChallenge]:
    require_verified_email(user)
    return db.scalars(
        select(models.SavingsChallenge).where(
            models.SavingsChallenge.user_id == user.id
        ).order_by(models.SavingsChallenge.created_at.desc())
    ).all()


@app.patch("/api/savings-challenges/{challenge_id}", response_model=schemas.SavingsChallenge)
def update_savings_challenge(
    challenge_id: int,
    payload: schemas.SavingsChallengeUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.SavingsChallenge:
    require_verified_email(user)
    challenge = db.scalar(
        select(models.SavingsChallenge).where(
            models.SavingsChallenge.id == challenge_id,
            models.SavingsChallenge.user_id == user.id,
        )
    )
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    today = datetime.now(UTC).date()
    old_amount = float(challenge.current_amount)
    challenge.current_amount = payload.current_amount

    if payload.current_amount > old_amount and challenge.last_contribution_date:
        gap = (today - challenge.last_contribution_date).days
        if gap <= 2:
            challenge.streak_days += gap
        else:
            challenge.streak_days = 1
    else:
        challenge.streak_days = max(challenge.streak_days, 1)

    challenge.last_contribution_date = today

    if float(payload.current_amount) >= float(challenge.target_amount):
        challenge.completed = True

    db.commit()
    db.refresh(challenge)
    return challenge


# ──────────────────────────────────────────────────────────────
# Feature 3: Split Expenses
# ──────────────────────────────────────────────────────────────

@app.post("/api/split-groups", response_model=schemas.SplitGroup, status_code=status.HTTP_201_CREATED)
def create_split_group(
    payload: schemas.SplitGroupCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.SplitGroup:
    require_verified_email(user)
    group = models.SplitGroup(
        user_id=user.id,
        name=payload.name,
        created_at=datetime.now(UTC),
    )
    db.add(group)
    db.flush()
    member = models.SplitMember(group_id=group.id, name=user.first_name or user.name, email=user.email)
    db.add(member)
    db.commit()
    db.refresh(group)
    return group


@app.get("/api/split-groups", response_model=list[schemas.SplitGroupRead])
def list_split_groups(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[dict]:
    require_verified_email(user)
    groups = db.scalars(
        select(models.SplitGroup).where(models.SplitGroup.user_id == user.id)
    ).all()
    result = []
    for g in groups:
        members = [{"id": m.id, "name": m.name, "email": m.email} for m in g.members]
        expenses = db.scalars(
            select(models.SplitExpense).where(models.SplitExpense.group_id == g.id)
        ).all()
        total = sum(float(e.amount) for e in expenses)
        unsettled = sum(float(e.amount) for e in expenses if not e.settled)
        result.append({
            "id": g.id,
            "name": g.name,
            "created_at": g.created_at,
            "members": members,
            "total_expenses": Decimal(str(total)),
            "unsettled_amount": Decimal(str(unsettled)),
        })
    return result


@app.post("/api/split-groups/{group_id}/members")
async def add_split_member(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    group = db.scalar(
        select(models.SplitGroup).where(
            models.SplitGroup.id == group_id,
            models.SplitGroup.user_id == user.id,
        )
    )
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Split group not found")
    data = await request.json()
    name = data.get("name", "")
    email = data.get("email", "")
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required")
    member = models.SplitMember(group_id=group_id, name=name, email=email)
    db.add(member)
    db.commit()
    return {"id": member.id, "name": member.name, "email": member.email}


@app.post("/api/split-expenses", response_model=schemas.SplitExpense, status_code=status.HTTP_201_CREATED)
def create_split_expense(
    payload: schemas.SplitExpenseCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.SplitExpense:
    require_verified_email(user)
    group = db.scalar(
        select(models.SplitGroup).where(
            models.SplitGroup.id == payload.split_group_id,
            models.SplitGroup.user_id == user.id,
        )
    )
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Split group not found")
    expense = models.SplitExpense(
        group_id=payload.split_group_id,
        description=payload.description,
        amount=payload.amount,
        paid_by_member_id=payload.paid_by,
        split_type=payload.split_type,
        splits=payload.splits,
        date=payload.date,
        created_at=datetime.now(UTC),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@app.get("/api/split-groups/{group_id}/expenses")
def list_split_expenses(
    group_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    group = db.scalar(
        select(models.SplitGroup).where(
            models.SplitGroup.id == group_id,
            models.SplitGroup.user_id == user.id,
        )
    )
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Split group not found")
    expenses = db.scalars(
        select(models.SplitExpense).where(models.SplitExpense.group_id == group_id)
        .order_by(models.SplitExpense.date.desc())
    ).all()
    return [
        {
            "id": e.id, "description": e.description, "amount": float(e.amount),
            "paid_by_member_id": e.paid_by_member_id, "split_type": e.split_type,
            "splits": e.splits, "date": e.date.isoformat(), "settled": e.settled,
        }
        for e in expenses
    ]


# ──────────────────────────────────────────────────────────────
# Feature 8: Multi-Currency Conversion on Entry
# ──────────────────────────────────────────────────────────────

@app.get("/api/currencies/convert")
def convert_currency(
    amount: float = 1,
    from_currency: str = "USD",
    to_currency: str = "USD",
    redis = Depends(get_redis),
):
    if from_currency == to_currency:
        return {"amount": amount, "from": from_currency, "to": to_currency, "converted": amount, "rate": 1}
    rates = get_exchange_rates(redis)
    if not rates:
        raise HTTPException(status_code=503, detail="Exchange rate service unavailable")
    from_rate = Decimal(str(rates.get(from_currency, 1)))
    to_rate = Decimal(str(rates.get(to_currency, 1)))
    converted = Decimal(str(amount)) / from_rate * to_rate
    rate = to_rate / from_rate
    return {
        "amount": amount,
        "from": from_currency,
        "to": to_currency,
        "converted": float(converted.quantize(Decimal("0.01"))),
        "rate": float(rate.quantize(Decimal("0.0001"))),
    }


# ──────────────────────────────────────────────────────────────
# Feature 9: Group Budgets
# ──────────────────────────────────────────────────────────────

@app.post("/api/group-budgets", response_model=schemas.GroupBudget, status_code=status.HTTP_201_CREATED)
def create_group_budget(
    payload: schemas.GroupBudgetCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.GroupBudget:
    require_verified_email(user)
    budget = models.GroupBudget(
        user_id=user.id,
        name=payload.name,
        total_budget=payload.total_budget,
        spent=0,
        members={"member_ids": payload.member_ids},
        start_date=payload.start_date,
        end_date=payload.end_date,
        created_at=datetime.now(UTC),
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


@app.get("/api/group-budgets", response_model=list[schemas.GroupBudget])
def list_group_budgets(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.GroupBudget]:
    require_verified_email(user)
    return db.scalars(
        select(models.GroupBudget).where(models.GroupBudget.user_id == user.id)
        .order_by(models.GroupBudget.created_at.desc())
    ).all()


@app.patch("/api/group-budgets/{budget_id}")
async def update_group_budget(
    budget_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    budget = db.scalar(
        select(models.GroupBudget).where(
            models.GroupBudget.id == budget_id,
            models.GroupBudget.user_id == user.id,
        )
    )
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group budget not found")
    data = await request.json()
    if "spent" in data:
        budget.spent = Decimal(str(data["spent"]))
    db.commit()
    db.refresh(budget)
    return budget


# ──────────────────────────────────────────────────────────────
# Feature: Budget Sharing (Multi-user)
# ──────────────────────────────────────────────────────────────

@app.post("/api/budget-shares", response_model=schemas.BudgetShareRead, status_code=status.HTTP_201_CREATED)
def create_budget_share(
    payload: schemas.BudgetShareCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.BudgetShare:
    require_verified_email(user)
    share_token = secrets.token_urlsafe(32)
    categories = db.scalars(
        select(models.Category).where(models.Category.user_id == user.id)
    ).all()
    budget_data = {
        "allowance": float(user.allowance or 0),
        "categories": [{"name": c.name, "budget": float(c.budget), "color": c.color} for c in categories],
    }
    share = models.BudgetShare(
        owner_user_id=user.id,
        shared_with_email=payload.shared_with_email.lower().strip(),
        share_token=share_token,
        budget_data=budget_data,
        created_at=datetime.now(UTC),
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return share


@app.get("/api/budget-shares", response_model=list[schemas.BudgetShareRead])
def list_budget_shares(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.BudgetShare]:
    require_verified_email(user)
    return db.scalars(
        select(models.BudgetShare).where(
            models.BudgetShare.owner_user_id == user.id,
            models.BudgetShare.active == True,
        ).order_by(models.BudgetShare.created_at.desc())
    ).all()


@app.get("/api/budget-shares/received", response_model=list[schemas.BudgetShareRead])
def list_received_budget_shares(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.BudgetShare]:
    require_verified_email(user)
    return db.scalars(
        select(models.BudgetShare).where(
            models.BudgetShare.shared_with_email == user.email.lower(),
            models.BudgetShare.active == True,
        ).order_by(models.BudgetShare.created_at.desc())
    ).all()


@app.post("/api/budget-shares/{share_id}/accept", response_model=schemas.MessageRead)
def accept_budget_share(
    share_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    require_verified_email(user)
    share = db.scalar(
        select(models.BudgetShare).where(
            models.BudgetShare.id == share_id,
            models.BudgetShare.shared_with_email == user.email.lower(),
            models.BudgetShare.active == True,
        )
    )
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    share.accepted_at = datetime.now(UTC)
    db.commit()
    return {"message": "Budget share accepted"}


@app.delete("/api/budget-shares/{share_id}", response_model=schemas.MessageRead)
def revoke_budget_share(
    share_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    require_verified_email(user)
    share = db.scalar(
        select(models.BudgetShare).where(
            models.BudgetShare.id == share_id,
            models.BudgetShare.owner_user_id == user.id,
        )
    )
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    share.active = False
    db.commit()
    return {"message": "Budget share revoked"}


# ──────────────────────────────────────────────────────────────
# Feature 10: Tax Deduction Tracker
# ──────────────────────────────────────────────────────────────

@app.get("/api/tax/categories", response_model=list[schemas.TaxCategory])
def list_tax_categories():
    cats = [
        {"id": 1, "name": "Tuition & Fees", "description": "Qualified tuition and fees", "deductible_percentage": 100},
        {"id": 2, "name": "Textbooks & Supplies", "description": "Required books and course materials", "deductible_percentage": 100},
        {"id": 3, "name": "Student Loan Interest", "description": "Interest on qualified student loans", "deductible_percentage": 100},
        {"id": 4, "name": "Transportation", "description": "Transportation to and from institution", "deductible_percentage": 50},
        {"id": 5, "name": "Equipment & Technology", "description": "Computer and equipment for education", "deductible_percentage": 100},
        {"id": 6, "name": "Other Education", "description": "Other qualified education expenses", "deductible_percentage": 50},
    ]
    return cats


@app.get("/api/tax/summary")
def get_tax_summary(
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    query = select(models.Expense).where(
        models.Expense.user_id == user.id,
        models.Expense.deleted == False,
        models.Expense.tax_deductible == True,
    )
    if start_date:
        query = query.where(models.Expense.date >= start_date)
    if end_date:
        query = query.where(models.Expense.date <= end_date)

    expenses = db.scalars(query.order_by(models.Expense.date)).all()

    category_totals: dict[str, float] = {}
    for e in expenses:
        cat = e.tax_category or "Uncategorized"
        category_totals[cat] = category_totals.get(cat, 0) + float(e.amount)

    total = sum(category_totals.values())
    return {
        "total_deductible": round(total, 2),
        "by_category": [{"category": k, "amount": round(v, 2)} for k, v in sorted(category_totals.items())],
        "expense_count": len(expenses),
    }


@app.patch("/api/expenses/{expense_id}/tax")
async def update_expense_tax_info(
    expense_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    expense = db.scalar(
        select(models.Expense).where(models.Expense.id == expense_id, models.Expense.user_id == user.id)
    )
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    data = await request.json()
    if "tax_deductible" in data:
        expense.tax_deductible = data["tax_deductible"]
    if "tax_category" in data:
        expense.tax_category = data["tax_category"]
    db.commit()
    invalidate_state_cache(user.id)
    return {"message": "Tax info updated"}


# ──────────────────────────────────────────────────────────────
# Feature 11: Dark Mode Preference
# ──────────────────────────────────────────────────────────────

@app.patch("/api/settings/dark-mode")
async def update_dark_mode(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    data = await request.json()
    settings = db.scalars(select(models.UserSettings).where(models.UserSettings.user_id == user.id)).first()
    if settings:
        settings.dark_mode = data.get("dark_mode", False)
        db.commit()
    return {"dark_mode": settings.dark_mode if settings else False}


# ──────────────────────────────────────────────────────────────
# Feature 12: Push Notifications
# ──────────────────────────────────────────────────────────────

@app.post("/api/push/subscribe")
async def subscribe_push(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    data = await request.json()
    existing = db.scalar(
        select(models.PushSubscription).where(
            models.PushSubscription.user_id == user.id,
            models.PushSubscription.endpoint == data.get("endpoint", ""),
        )
    )
    if existing:
        existing.p256dh = data.get("keys", {}).get("p256dh", "")
        existing.auth_key = data.get("keys", {}).get("auth", "")
        existing.active = True
    else:
        sub = models.PushSubscription(
            user_id=user.id,
            endpoint=data.get("endpoint", ""),
            p256dh=data.get("keys", {}).get("p256dh", ""),
            auth_key=data.get("keys", {}).get("auth", ""),
            active=True,
            created_at=datetime.now(UTC),
        )
        db.add(sub)
    db.commit()
    return {"message": "Push subscription saved"}


@app.post("/api/push/unsubscribe")
async def unsubscribe_push(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    data = await request.json()
    sub = db.scalar(
        select(models.PushSubscription).where(
            models.PushSubscription.user_id == user.id,
            models.PushSubscription.endpoint == data.get("endpoint", ""),
        )
    )
    if sub:
        sub.active = False
        db.commit()
    return {"message": "Push subscription removed"}


# ──────────────────────────────────────────────────────────────
# Feature 13: Enhanced Financial Health Score
# ──────────────────────────────────────────────────────────────

@app.get("/api/analytics/health-score")
def get_health_score(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    require_verified_email(user)
    today = datetime.now(UTC).date()
    month_start = today.replace(day=1)

    expenses = db.scalars(
        select(models.Expense).where(
            models.Expense.user_id == user.id,
            models.Expense.deleted == False,
            models.Expense.date >= month_start,
        )
    ).all()

    allowance = float(user.allowance or 0)
    total_spent = sum(float(e.amount) for e in expenses)

    budget_score = max(0, min(30, 30 * (1 - total_spent / allowance))) if allowance > 0 else 15

    categories_used = len(set(e.category for e in expenses))
    diversity_score = min(20, categories_used * 4)

    recurring = db.scalars(
        select(models.RecurringExpense).where(models.RecurringExpense.user_id == user.id)
    ).all()
    planning_score = min(20, len(recurring) * 7)

    days_elapsed = (today - month_start).days + 1
    daily_rate = total_spent / max(days_elapsed, 1)
    days_in_month = (today.replace(month=today.month % 12 + 1, day=1) - timedelta(days=1)).day if today.month < 12 else 31
    projected = daily_rate * days_in_month
    consistency_score = max(0, min(15, 15 * (1 - max(0, projected - allowance) / allowance))) if allowance > 0 else 7

    savings_goal = db.scalars(
        select(models.Goal).where(models.Goal.user_id == user.id)
    ).first()
    savings_score = 0
    if savings_goal and float(savings_goal.target) > 0:
        savings_pct = float(savings_goal.saved) / float(savings_goal.target)
        savings_score = min(15, savings_pct * 15)

    total_score = round(budget_score + diversity_score + planning_score + consistency_score + savings_score)

    if total_score >= 80:
        grade = "Excellent"
        message = "Your financial habits are strong. Keep it up!"
    elif total_score >= 60:
        grade = "Good"
        message = "Solid foundation. Consider adding more recurring expenses or increasing savings."
    elif total_score >= 40:
        grade = "Fair"
        message = "Room for improvement. Try setting category budgets and tracking more consistently."
    else:
        grade = "Needs Attention"
        message = "Start by setting a monthly allowance and creating a savings goal."

    return {
        "score": total_score,
        "grade": grade,
        "message": message,
        "breakdown": {
            "budget_discipline": round(budget_score),
            "category_diversity": round(diversity_score),
            "planning": round(planning_score),
            "consistency": round(consistency_score),
            "savings_progress": round(savings_score),
        },
    }


# ──────────────────────────────────────────────────────────────
# Feature 15: Student Discount Finder
# ──────────────────────────────────────────────────────────────

DISCOUNT_DATABASE = [
    {"provider": "Amazon", "category": "Shopping", "discount": "50% off Prime Student", "url": "https://www.amazon.com/primestudent", "requires_verification": True},
    {"provider": "Apple", "category": "Technology", "discount": "Education pricing on Mac & iPad", "url": "https://www.apple.com/shop/go/education", "requires_verification": True},
    {"provider": "Spotify", "category": "Entertainment", "discount": "50% off Premium for students", "url": "https://www.spotify.com/student", "requires_verification": True},
    {"provider": "Adobe", "category": "Software", "discount": "60% off Creative Cloud", "url": "https://www.adobe.com/creativecloud/plans.html", "requires_verification": True},
    {"provider": "Microsoft", "category": "Software", "discount": "Free Office 365 Education", "url": "https://www.microsoft.com/en-us/education/products/office", "requires_verification": True},
    {"provider": "GitHub", "category": "Technology", "discount": "Free GitHub Pro", "url": "https://education.github.com", "requires_verification": True},
    {"provider": "Notion", "category": "Productivity", "discount": "Free Plus plan for students", "url": "https://www.notion.so/product/notion-for-education", "requires_verification": True},
    {"provider": "Canva", "category": "Design", "discount": "Free Canva Pro for students", "url": "https://www.canva.com/canva-for-education/", "requires_verification": True},
    {"provider": "Autodesk", "category": "Design", "discount": "Free education license", "url": "https://www.autodesk.com/education/edu-software/overview", "requires_verification": True},
    {"provider": "JetBrains", "category": "Technology", "discount": "Free all-products pack", "url": "https://www.jetbrains.com/student/", "requires_verification": True},
    {"provider": "Overleaf", "category": "Productivity", "discount": "Free Overleaf subscription", "url": "https://www.overleaf.com/user/subscription/edu", "requires_verification": True},
    {"provider": "Coursera", "category": "Education", "discount": "Financial aid available", "url": "https://www.coursera.org/financial-aid", "requires_verification": False},
]


@app.get("/api/discounts")
def list_student_discounts(category: str = ""):
    if category:
        return [d for d in DISCOUNT_DATABASE if d["category"].lower() == category.lower()]
    return DISCOUNT_DATABASE


@app.get("/api/discounts/categories")
def list_discount_categories():
    return list(set(d["category"] for d in DISCOUNT_DATABASE))
