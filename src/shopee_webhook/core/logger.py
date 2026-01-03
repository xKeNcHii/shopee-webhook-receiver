"""Logging configuration and setup."""

import json
import logging
import os
import sys
import time
import traceback
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

# Get log level from environment
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Create logs directory
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Singapore timezone
SG_TZ = ZoneInfo("Asia/Singapore")

# Generate session ID (for distinguishing multiple app starts on same day)
SESSION_ID = str(uuid.uuid4())[:8]

# Create date-based log filename with session ID (Singapore time)
LOG_DATE = datetime.now(SG_TZ).strftime("%Y-%m-%d")
LOG_FILENAME = f"webhook_{LOG_DATE}_{SESSION_ID}.log"


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON (Singapore timezone)."""
        log_data = {
            "timestamp": datetime.now(SG_TZ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Add extra fields if present
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        return json.dumps(log_data, default=str)


# Configure root logger once
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# Skip if already configured
if not root_logger.handlers:
    # File handler (date and session-based, no rotation needed)
    file_handler = logging.FileHandler(log_dir / LOG_FILENAME)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())

    # Console handler (JSON format)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    console_handler.setFormatter(JSONFormatter())

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def setup_logger(name: str) -> logging.Logger:
    """Get logger for a module."""
    logger = logging.getLogger(name)
    logger.propagate = True
    return logger


logger = setup_logger("shopee_webhook")
