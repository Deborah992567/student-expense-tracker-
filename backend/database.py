from collections.abc import Generator
import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings

logger = logging.getLogger(__name__)


def ensure_database_exists(url: str) -> None:
    parsed = make_url(url)

    if parsed.drivername.startswith("sqlite"):
        db_path = parsed.database
        if db_path and db_path != ":memory:":
            db_file = Path(db_path)
            if not db_file.is_absolute():
                db_file = Path.cwd() / db_file
            db_file.parent.mkdir(parents=True, exist_ok=True)
            logger.info("SQLite database path ensured: %s", db_file)
        return

    if not parsed.drivername.startswith("mysql"):
        return

    database_name = parsed.database
    if not database_name:
        return

    server_url = parsed.set(database="")
    logger.info("Ensuring MySQL database exists: %s", database_name)
    try:
        engine_for_create = create_engine(server_url, pool_pre_ping=True)
        with engine_for_create.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            conn.commit()
    except OperationalError as exc:
        message = str(exc)
        if "1045" in message or "Access denied" in message:
            raise RuntimeError(
                "MySQL authentication failed while initializing the database. "
                "Check backend/.env DATABASE_URL credentials or switch to SQLite for development."
            ) from exc
        logger.warning(
            "Unable to connect to MySQL server to create database %s: %s",
            database_name,
            exc,
        )
        raise
    finally:
        if 'engine_for_create' in locals():
            engine_for_create.dispose()


class Base(DeclarativeBase):
    pass


# Get database URL from settings
db_url = get_settings().database_url
logger.info(
    "Initializing database connection to: %s",
    db_url.split("@")[-1].split("/", 1)[-1] if "@" in db_url else db_url
)

ensure_database_exists(db_url)

is_sqlite = db_url.startswith("sqlite")

engine = create_engine(
    db_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if is_sqlite else {},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)


@event.listens_for(engine, "connect")
def on_connect(dbapi_conn, connection_record):
    """Log when a new database connection is established."""
    logger.debug("New database connection established")


@event.listens_for(engine, "checkout")
def on_checkout(dbapi_conn, connection_record, connection_proxy):
    """Log when a connection is checked out from the pool."""
    logger.debug("Database connection checked out from pool")


@event.listens_for(engine, "checkin")
def on_checkin(dbapi_conn, connection_record, connection_proxy=None):
    """Log when a connection is returned to the pool.

    Some SQLAlchemy versions pass a `connection_proxy` as the third
    positional argument to checkin/listener functions. Accept it
    optionally to remain compatible across versions.
    """
    logger.debug("Database connection returned to pool")


def get_db() -> Generator[Session, None, None]:
    """Get a database session."""
    db = SessionLocal()

    try:
        logger.debug("Database session opened")
        yield db

    except HTTPException:
        raise

    except Exception as e:
        logger.error("Database session error: %s", str(e))
        raise

    finally:
        db.close()
        logger.debug("Database session closed")