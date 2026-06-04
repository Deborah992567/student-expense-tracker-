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
    ensure_user_range_columns()
    ensure_security_columns()
    ensure_two_factor_columns()
    ensure_expense_archive_columns()
    ensure_refresh_token_device_columns()
    ensure_database_indexes()
    reset_legacy_starter_budgets()
    reset_legacy_starter_goals()
    seed_default_feature_flags()
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

    user = models.User(
        name=f"{payload.first_name.strip()} {payload.last_name.strip()}",
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        gender=payload.gender,
        email=email,
        password_hash=hash_password(payload.password),
        role="admin" if db.scalar(select(func.count(models.User.id))) == 0 else "student",
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
    
    logger.info("User signup successful: user_id=%s, email=%s", user.id, email)
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
def forgot_password(payload: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    email = normalize_email(payload.email)
    user = db.scalar(select(models.User).where(models.User.email == email))

    # Always return the same message regardless of whether the email exists
    # This prevents email enumeration attacks
    # TODO: Implement password reset token generation and email delivery
    return {"message": "If an account exists with this email, password reset instructions will be sent."}


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
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, object]:
    require_verified_email(user)
    query = select(models.Expense).where(models.Expense.user_id == user.id, models.Expense.deleted == True).order_by(models.Expense.deleted_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    expenses = db.scalars(query.limit(per_page).offset((page - 1) * per_page)).all()
    pagination = schemas.PaginationInfo(
        page=page,
        per_page=per_page,
        total=int(total or 0),
        total_pages=(int(total or 0) + per_page - 1) // per_page,
        has_next=((page * per_page) < (int(total or 0))),
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
    if active and report.next_run_at < datetime.now(UTC):
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
            command = ["pg_dump", str(url), "-Fc", "-f", str(destination)]
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
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
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created ON notifications (user_id, read, created_at)",
    ]
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for statement in index_statements:
            table_name = statement.split(" ON ", 1)[1].split(" ", 1)[0]
            if table_name in tables:
                connection.execute(text(statement))


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
