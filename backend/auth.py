import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
import redis
from redis.exceptions import RedisError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import models
from backend.config import get_settings
from backend.database import get_db
from backend.logging_config import get_logger, get_security_logger

logger = get_logger(__name__)
security_logger = get_security_logger()

LEGACY_PASSWORD_ALGORITHM = "pbkdf2_sha256"
LEGACY_PASSWORD_ITERATIONS = 260_000
JWT_ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12

bearer_scheme = HTTPBearer(auto_error=False)

# Initialize Redis client (usually this would be in database.py or config.py)
try:
    redis_client = redis.from_url(get_settings().redis_url, decode_responses=True)
except Exception as e:
    logger.error("Failed to connect to Redis: %s", e)
    redis_client = None

def get_redis():
    if not redis_client:
        return None
    return redis_client

def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith(f"{LEGACY_PASSWORD_ALGORITHM}$"):
        return _verify_legacy_password(password, stored_hash)

    if not stored_hash.startswith("$2"):
        return False

    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))


def needs_password_rehash(stored_hash: str) -> bool:
    if stored_hash.startswith(f"{LEGACY_PASSWORD_ALGORITHM}$"):
        return True

    if not stored_hash.startswith("$2"):
        return True

    try:
        return int(stored_hash.split("$", 3)[2]) < BCRYPT_ROUNDS
    except (IndexError, ValueError):
        return True


def create_access_token(user: models.User) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": datetime.now(UTC),
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, object]:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[JWT_ALGORITHM])
    except InvalidTokenError:
        raise _auth_error() from None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _auth_error()

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise _auth_error()

    try:
        user = db.get(models.User, int(user_id))
    except ValueError:
        raise _auth_error() from None

    if user is None:
        raise _auth_error()

    if not hasattr(user, "role"):
        user.role = "student"

    return user


def require_role(user: models.User, required_role: str) -> None:
    if getattr(user, "role", "student") != required_role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def authenticate_user(db: Session, email: str, password: str) -> models.User | None:
    normalized_email = normalize_email(email)
    user = db.scalar(select(models.User).where(models.User.email == normalized_email))
    
    if user is None:
        logger.warning("Authentication failed: user not found for email=%s", normalized_email)
        return None
    
    if not verify_password(password, user.password_hash):
        logger.warning("Authentication failed: invalid password for email=%s", normalized_email)
        return None

    if needs_password_rehash(user.password_hash):
        logger.info("Rehashing password for user_id=%s", user.id)
        user.password_hash = hash_password(password)
        db.commit()
        db.refresh(user)

    logger.info("User authenticated successfully: user_id=%s, email=%s", user.id, normalized_email)
    return user


def normalize_email(email: str) -> str:
    return email.lower().strip()


def check_login_rate_limit(email: str) -> None:
    if not redis_client:
        return # Fallback or skip if Redis isn't ready
        
    key = normalize_email(email)
    redis_key = f"login_attempts:{key}"
    
    try:
        attempts = redis_client.get(redis_key)
        if attempts and int(attempts) >= get_settings().login_max_attempts:
            security_logger.warning(
                "Rate limit exceeded: email=%s, attempts=%s",
                key, attempts
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Try again later.",
            )
    except RedisError as e:
        logger.error("Redis error in check_login_rate_limit: %s", e)


def record_failed_login(email: str) -> None:
    if not redis_client:
        return
        
    key = normalize_email(email)
    redis_key = f"login_attempts:{key}"
    
    try:
        attempts = redis_client.incr(redis_key)
        # Set expiry on first failure
        if attempts == 1:
            redis_client.expire(redis_key, get_settings().login_lockout_minutes * 60)
            
        if attempts >= get_settings().login_max_attempts:
            security_logger.warning(
                "Account locked due to too many failed attempts: email=%s, attempts=%d, lockout_minutes=%d",
                key, attempts, get_settings().login_lockout_minutes
            )
    except RedisError as e:
        logger.error("Redis error in record_failed_login: %s", e)

def clear_failed_logins(email: str) -> None:
    if not redis_client:
        return
    try:
        redis_client.delete(f"login_attempts:{normalize_email(email)}")
    except RedisError as e:
        logger.error("Redis error in clear_failed_logins: %s", e)

def check_api_rate_limit(user_id: int) -> None:
    """General API rate limiting using Redis."""
    if not redis_client:
        return
        
    key = f"rate_limit:api:{user_id}"
    try:
        attempts = redis_client.get(key)
        
        if attempts and int(attempts) >= get_settings().api_rate_limit_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="API rate limit exceeded. Please wait a minute.",
            )
        
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        pipe.execute()
    except RedisError as e:
        logger.error("Redis error in check_api_rate_limit: %s", e)

def invalidate_state_cache(user_id: int) -> None:
    """Invalidate the cached app state for a specific user."""
    if not redis_client:
        return
    try:
        redis_client.delete(f"state:{user_id}")
    except RedisError as e:
        logger.error("Redis error in invalidate_state_cache: %s", e)


def _auth_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _verify_legacy_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored_hash.split("$", 3)
        if algorithm != LEGACY_PASSWORD_ALGORITHM:
            return False

        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _b64decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(_b64encode(candidate), digest)
    except (ValueError, TypeError):
        return False


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# Refresh token helpers
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_refresh_token(db: Session, user: models.User):
    settings = get_settings()
    plaintext = secrets.token_urlsafe(48)
    jti = secrets.token_hex(16)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.refresh_token_days)
    token_hash = _hash_token(plaintext)
    rt = models.RefreshToken(
        jti=jti,
        user_id=user.id,
        token_hash=token_hash,
        created_at=now,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)
    return plaintext, rt


def verify_refresh_token(db: Session, plaintext: str):
    token_hash = _hash_token(plaintext)
    rt = db.scalar(select(models.RefreshToken).where(models.RefreshToken.token_hash == token_hash))
    if rt is None:
        return None
    if rt.revoked:
        # Possible token reuse: revoke all refresh tokens for this user and log security event
        try:
            user = db.get(models.User, rt.user_id)
            security_logger.warning(
                "Refresh token reuse detected: user_id=%s, jti=%s",
                rt.user_id, rt.jti,
            )
            # Revoke all tokens for this user to mitigate reuse
            revoke_all_user_tokens(db, user)
        except Exception:
            logger.exception("Error handling refresh token reuse for jti=%s", rt.jti)
        return None
    if rt.expires_at < datetime.now(UTC):
        return None
    return rt


def revoke_refresh_token(db: Session, rt: models.RefreshToken):
    rt.revoked = True
    db.add(rt)
    db.commit()


def revoke_all_user_tokens(db: Session, user: models.User):
    db.query(models.RefreshToken).filter(models.RefreshToken.user_id == user.id, models.RefreshToken.revoked == False).update({"revoked": True})
    db.commit()
