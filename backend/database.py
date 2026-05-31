from collections.abc import Generator
import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# Get database URL from settings
db_url = get_settings().database_url
logger.info(
    "Initializing database connection to: %s",
    db_url.split("@")[-1].split("/", 1)[-1] if "@" in db_url else db_url
)

engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True
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

    except Exception as e:
        logger.error("Database session error: %s", str(e))
        raise

    finally:
        db.close()
        logger.debug("Database session closed")