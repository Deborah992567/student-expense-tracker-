from datetime import UTC, datetime, date as date_type
from decimal import Decimal
from pathlib import Path
import sys
import time
import json
import csv
import io
import urllib.request

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status, Query, Request
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
    verify_refresh_token,
    revoke_refresh_token,
    revoke_all_user_tokens,
    check_api_rate_limit,
    invalidate_state_cache,
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
from backend.seed import seed_user_defaults

# Setup logging
setup_logging()

app = FastAPI(title="StudentSpend API")
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
    
    # Store client IP in request state for later use
    request.state.client_ip = request.client.host if request.client else "unknown"
    
    # Log incoming request
    access_logger.info(
        "Request started: method=%s path=%s client=%s",
        request.method, request.url.path, request.state.client_ip
    )
    
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Log response
        access_logger.info(
            "Request completed: method=%s path=%s status=%d duration=%.3fs",
            request.method, request.url.path, response.status_code, duration
        )
        
        return response
    except Exception as e:
        duration = time.time() - start_time
        # Handle specific SQLAlchemy errors globally
        if "UniqueViolation" in str(e) or "duplicate key" in str(e).lower():
             return Response(
                content=json.dumps({"detail": "This record already exists."}),
                status_code=409,
                media_type="application/json"
            )
            
        logger.error(
            "Request failed: method=%s path=%s error=%s duration=%.3fs",
            request.method, request.url.path, str(e), duration,
            exc_info=True
        )
        raise


@app.on_event("startup")
def startup() -> None:
    logger.info("Starting StudentSpend API server...")
    Base.metadata.create_all(bind=engine)
    ensure_user_profile_columns()
    ensure_user_range_columns()
    reset_legacy_starter_budgets()
    reset_legacy_starter_goals()
    logger.info("StudentSpend API server started successfully")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/{asset_name}", include_in_schema=False)
def frontend_asset(asset_name: str) -> FileResponse:
    allowed_assets = {"app.js", "styles.css"}
    if asset_name not in allowed_assets:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return FileResponse(FRONTEND_DIR / asset_name, headers={"Cache-Control": "no-store"})


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
    )
    db.add(user)
    db.flush()
    seed_user_defaults(db, user)
    db.commit()
    db.refresh(user)
    background_send_verification(db, user, background_tasks)
    
    logger.info("User signup successful: user_id=%s, email=%s", user.id, email)
    security_logger.info("New user registered: user_id=%s, email=%s", user.id, email)
    return {"access_token": create_access_token(user), "profile": user}


@app.post("/api/auth/login", response_model=schemas.TokenRead)
def login(payload: schemas.LoginRequest, request: Request, response: Response, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict[str, object]:
    email = normalize_email(payload.email)
    client_ip = getattr(request.state, "client_ip", "unknown")
    logger.debug("Login attempt for email=%s, ip=%s", email, client_ip)
    
    check_login_rate_limit(payload.email)
    user = authenticate_user(db, payload.email, payload.password)
    if user is None:
        record_failed_login(payload.email)
        security_logger.warning("Failed login attempt: email=%s, ip=%s", email, client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    clear_failed_logins(payload.email)
    
    # Trigger background maintenance
    background_tasks.add_task(cleanup_expired_data)
    background_tasks.add_task(process_recurring_expenses, user.id)
    
    logger.info("Login successful: user_id=%s, email=%s, ip=%s", user.id, email, client_ip)
    token = create_access_token(user)
    # create refresh token and set as cookie
    try:
        plaintext, rt = create_refresh_token(db, user)
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

    # rotate: revoke current and issue a new one
    try:
        revoke_refresh_token(db, rt)
        plaintext, new_rt = create_refresh_token(db, user)
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
            background_tasks.add_task(
                send_budget_limit_email,
                user.email,
                user.first_name or user.name,
                alert_category.name,
                float(category_spent / alert_category.budget * 100),
                float(alert_category.budget),
            )
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
    start_date: str = "",
    end_date: str = "",
    min_amount: float = 0,
    max_amount: float = 0,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, object]:
    require_verified_email(user)

    # Validate pagination
    page = max(1, page)
    per_page = min(max(1, per_page), 100)

    # Build query
    query = select(models.Expense).where(models.Expense.user_id == user.id)

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
    count_query = select(models.Expense.id).where(models.Expense.user_id == user.id)
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
    query = query.order_by(models.Expense.date.desc(), models.Expense.id.desc())
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
