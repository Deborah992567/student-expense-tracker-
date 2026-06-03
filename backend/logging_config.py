"""
Production logging configuration for the StudentSpend application.

Configures structured logging with:
- Console output for development
- File output with rotation for production
- JSON-formatted logs for production (optional)
- Appropriate log levels per environment
"""

import logging
import logging.handlers
import json
import sys
from pathlib import Path

from backend.config import get_settings


# Log directory
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Log file paths
INFO_LOG_FILE = LOG_DIR / "info.log"
ERROR_LOG_FILE = LOG_DIR / "error.log"
ACCESS_LOG_FILE = LOG_DIR / "access.log"
SECURITY_LOG_FILE = LOG_DIR / "security.log"


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors to log levels for console output."""
    
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


class StructuredJSONFormatter(logging.Formatter):
    """JSON formatter that carries request/correlation metadata when present."""

    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in (
            "request_id",
            "correlation_id",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "client_ip",
            "api_version",
            "event",
            "user_id",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def setup_logging() -> None:
    """Configure logging for the application."""
    settings = get_settings()
    
    # Determine if we're in production mode (could be based on env var or debug setting)
    is_production = settings.secret_key != "change-this-dev-secret"
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if not is_production else logging.INFO)
    
    # Clear any existing handlers
    root_logger.handlers.clear()
    
    # Console handler (for development and immediate feedback)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if not is_production else logging.INFO)
    console_format = StructuredJSONFormatter()
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)
    
    # File handler for general info logs (production)
    if is_production:
        info_handler = logging.handlers.RotatingFileHandler(
            INFO_LOG_FILE,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8"
        )
        info_handler.setLevel(logging.INFO)
        info_format = StructuredJSONFormatter()
        info_handler.setFormatter(info_format)
        root_logger.addHandler(info_handler)
        
        # File handler for error logs
        error_handler = logging.handlers.RotatingFileHandler(
            ERROR_LOG_FILE,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8"
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(info_format)
        root_logger.addHandler(error_handler)
    
    # Set specific log levels for noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING if not is_production else logging.ERROR)
    
    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info("Logging configured successfully (mode: %s)", "production" if is_production else "development")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.
    
    Args:
        name: The name for the logger (usually __name__)
    
    Returns:
        A configured logger instance
    """
    return logging.getLogger(name)


# Security-specific logger
def get_security_logger() -> logging.Logger:
    """Get the security-specific logger for security-related events."""
    return logging.getLogger("security")


# Access-specific logger  
def get_access_logger() -> logging.Logger:
    """Get the access-specific logger for API access logging."""
    return logging.getLogger("access")
