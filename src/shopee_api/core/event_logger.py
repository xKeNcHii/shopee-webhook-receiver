#!/usr/bin/env python3
"""
Webhook Event Logger

Logs all incoming Shopee webhook events to daily JSONL files for analysis and debugging.
JSONL format allows easy parsing and streaming of events.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from shopee_api.core.logger import setup_logger

# Singapore timezone (UTC+8)
SINGAPORE_TZ = timezone(timedelta(hours=8))

logger = setup_logger(__name__)

# Create logs directory if it doesn't exist
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)


def log_webhook_event(
    event_code: int,
    shop_id: int,
    event_data: Dict[str, Any],
    authorization_header: Optional[str] = None,
    raw_body: Optional[str] = None,
    processing_status: Optional[Dict[str, Any]] = None
) -> str:
    """
    Log a webhook event to a daily rotating JSONL file.

    Each event is one JSON object per line (JSONL format) for easy streaming and parsing.

    Args:
        event_code: Shopee event code (e.g., 3 for Order Status Update)
        shop_id: Shop ID from the webhook
        event_data: Full event payload from webhook
        authorization_header: Authorization header (truncated for security)
        raw_body: Raw request body (optional, for debugging)
        processing_status: Processing status from Telegram/Forwarder (optional)

    Returns:
        Path to the log file where event was written
    """
    # Create filename based on current date in Singapore timezone
    date_str = datetime.now(SINGAPORE_TZ).strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"webhook_events_{date_str}.json"

    # Prepare log entry
    log_entry = {
        "timestamp": datetime.now(SINGAPORE_TZ).isoformat(),
        "event_code": event_code,
        "shop_id": shop_id,
        "event_data": event_data,
        "metadata": {
            "authorization": f"{authorization_header[:20]}..." if authorization_header else None,
            "body_size": len(raw_body) if raw_body else 0
        }
    }

    # Add processing status if provided (for dashboard monitoring)
    if processing_status:
        log_entry["processing_status"] = processing_status

    try:
        # Append to file (one JSON object per line for JSONL format)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        logger.info(f"Logged webhook event (code={event_code}, shop_id={shop_id}) to {log_file}")
        return str(log_file)

    except IOError as e:
        logger.error(f"Failed to write webhook event to log file: {e}")
        return str(log_file)
    except Exception as e:
        logger.error(f"Unexpected error logging webhook event: {e}")
        return str(log_file)


def get_log_file_for_date(date_str: str = None) -> Path:
    """
    Get the log file path for a specific date.

    Args:
        date_str: Date in YYYY-MM-DD format. If None, uses today's date.

    Returns:
        Path to the log file for that date
    """
    if date_str is None:
        date_str = datetime.now(SINGAPORE_TZ).strftime("%Y-%m-%d")

    return LOGS_DIR / f"webhook_events_{date_str}.json"


def read_events_from_log(date_str: str = None) -> list:
    """
    Read all webhook events from a log file.

    Args:
        date_str: Date in YYYY-MM-DD format. If None, uses today's date.

    Returns:
        List of event dictionaries
    """
    log_file = get_log_file_for_date(date_str)

    if not log_file.exists():
        logger.warning(f"Log file does not exist: {log_file}")
        return []

    events = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse line {line_num} in {log_file}: {e}")

        logger.info(f"Read {len(events)} events from {log_file}")
        return events

    except IOError as e:
        logger.error(f"Failed to read log file {log_file}: {e}")
        return []


def get_event_statistics(date_str: str = None) -> Dict[str, Any]:
    """
    Get statistics about webhook events for a given date.

    Args:
        date_str: Date in YYYY-MM-DD format. If None, uses today's date.

    Returns:
        Dictionary with event statistics
    """
    events = read_events_from_log(date_str)

    if not events:
        return {
            "date": date_str or datetime.now(SINGAPORE_TZ).strftime("%Y-%m-%d"),
            "total_events": 0,
            "events_by_code": {},
            "shops": []
        }

    # Count events by code
    events_by_code = {}
    shops = set()

    for event in events:
        code = event.get("event_code", "unknown")
        shop_id = event.get("shop_id", "unknown")

        events_by_code[code] = events_by_code.get(code, 0) + 1
        shops.add(shop_id)

    return {
        "date": date_str or datetime.now(SINGAPORE_TZ).strftime("%Y-%m-%d"),
        "total_events": len(events),
        "events_by_code": dict(sorted(events_by_code.items(), key=lambda x: (x[0] is None, x[0]))),
        "unique_shops": len(shops),
        "shops": sorted([s for s in shops if s is not None]) + ([None] if None in shops else [])
    }


if __name__ == "__main__":
    # Demo: Show statistics for today
    import sys

    if len(sys.argv) > 1:
        date = sys.argv[1]
    else:
        date = None

    stats = get_event_statistics(date)
    print(json.dumps(stats, indent=2))
