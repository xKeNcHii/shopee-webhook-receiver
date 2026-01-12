"""
Dashboard API Routes

REST API endpoints for webhook monitoring dashboard.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path
from datetime import date, datetime
from typing import List, Dict, Any

from shopee_api.server.auth import verify_api_key
from shopee_api.core.event_logger import read_events_from_log, get_event_statistics
from shopee_api.core.runtime_config import runtime_config
from shopee_api.core.logger import setup_logger

logger = setup_logger(__name__)

# Router with /api/dashboard prefix
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/events")
async def get_events(
    date_str: str = Query(default=None, description="Date in YYYY-MM-DD format"),
    limit: int = Query(default=10000, ge=1, le=10000, description="Max events to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    _: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get webhook events with processing status.

    Returns events from the specified date (or today) with Telegram and Forwarder
    processing status for dashboard monitoring.
    """
    if not date_str:
        date_str = date.today().strftime("%Y-%m-%d")

    try:
        events = read_events_from_log(date_str)
        total = len(events)

        # Return events in chronological order (oldest first)
        events_sorted = list(reversed(events))

        # Return paginated events
        return {
            "date": date_str,
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": events_sorted[offset:offset + limit]
        }
    except Exception as e:
        logger.error(f"Error getting events: {e}")
        return {
            "date": date_str,
            "total": 0,
            "limit": limit,
            "offset": offset,
            "events": [],
            "error": str(e)
        }


@router.get("/queue/stats")
async def get_queue_stats(_: bool = Depends(verify_api_key)) -> Dict[str, Any]:
    """
    Get Telegram queue statistics.

    Returns current queue status including:
    - Queue size (pending messages)
    - Messages sent/failed counts
    - Worker status
    - Messages per minute rate
    """
    try:
        from shopee_api.integrations.telegram_queue import get_message_queue

        queue = get_message_queue()
        stats = queue.get_stats()

        return {
            "success": True,
            "queue": stats
        }
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        return {
            "success": False,
            "error": str(e),
            "queue": {
                "is_running": False,
                "queue_size": 0,
                "total_queued": 0,
                "total_sent": 0,
                "total_failed": 0,
            }
        }


@router.get("/stats")
async def get_stats(_: bool = Depends(verify_api_key)) -> Dict[str, Any]:
    """
    Get webhook statistics for today.

    Returns aggregated stats including:
    - Total webhooks
    - Telegram success/failure counts
    - Forwarder success/failure counts
    - Recent errors
    """
    today = date.today().strftime("%Y-%m-%d")

    try:
        events = read_events_from_log(today)

        # Count telegram results
        telegram_success = 0
        telegram_failed = 0
        telegram_disabled = 0

        # Count forwarder results
        forwarder_success = 0
        forwarder_failed = 0
        forwarder_disabled = 0

        # Track recent errors
        recent_errors = []

        for event in events:
            processing_status = event.get("processing_status", {})

            # Telegram stats
            telegram_status = processing_status.get("telegram", {})
            if telegram_status.get("success"):
                telegram_success += 1
            elif telegram_status.get("success") is False:
                telegram_failed += 1
                if telegram_status.get("error"):
                    recent_errors.append({
                        "timestamp": event.get("timestamp"),
                        "event_code": event.get("event_code"),
                        "service": "telegram",
                        "error": telegram_status.get("error"),
                        "order_sn": event.get("event_data", {}).get("ordersn")
                    })
            else:
                telegram_disabled += 1

            # Forwarder stats
            forwarder_status = processing_status.get("forwarder", {})
            if forwarder_status.get("success"):
                forwarder_success += 1
            elif forwarder_status.get("success") is False:
                forwarder_failed += 1
                if forwarder_status.get("error"):
                    recent_errors.append({
                        "timestamp": event.get("timestamp"),
                        "event_code": event.get("event_code"),
                        "service": "forwarder",
                        "error": forwarder_status.get("error"),
                        "order_sn": event.get("event_data", {}).get("ordersn")
                    })
            else:
                forwarder_disabled += 1

        # Calculate success rates
        telegram_total = telegram_success + telegram_failed
        forwarder_total = forwarder_success + forwarder_failed

        telegram_rate = (telegram_success / telegram_total * 100) if telegram_total > 0 else 0
        forwarder_rate = (forwarder_success / forwarder_total * 100) if forwarder_total > 0 else 0

        # Get event statistics
        stats = get_event_statistics(today)

        return {
            "period": "today",
            "date": today,
            "generated_at": datetime.utcnow().isoformat(),
            "summary": {
                "total_webhooks": len(events),
                "telegram": {
                    "success": telegram_success,
                    "failed": telegram_failed,
                    "disabled": telegram_disabled,
                    "success_rate": round(telegram_rate, 2)
                },
                "forwarder": {
                    "success": forwarder_success,
                    "failed": forwarder_failed,
                    "disabled": forwarder_disabled,
                    "success_rate": round(forwarder_rate, 2)
                }
            },
            "by_event_code": stats.get("events_by_code", {}),
            "recent_errors": recent_errors  # All errors for the day
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {
            "period": "today",
            "date": today,
            "generated_at": datetime.utcnow().isoformat(),
            "summary": {
                "total_webhooks": 0,
                "telegram": {"success": 0, "failed": 0, "disabled": 0, "success_rate": 0},
                "forwarder": {"success": 0, "failed": 0, "disabled": 0, "success_rate": 0}
            },
            "by_event_code": {},
            "recent_errors": [],
            "error": str(e)
        }


@router.get("/config")
async def get_config(_: bool = Depends(verify_api_key)) -> Dict[str, Any]:
    """
    Get current configuration status.

    Returns masked configuration for Telegram and Forwarder,
    including whether runtime overrides are active.
    """
    try:
        # Get runtime config (overrides .env)
        telegram_cfg = runtime_config.get_telegram_config()
        forwarder_cfg = runtime_config.get_forwarder_config()
        glitchtip_cfg = runtime_config.get_glitchtip_config()

        # Mask sensitive data
        telegram_token = telegram_cfg.get("bot_token")
        telegram_token_masked = (
            telegram_token[:10] + "***" if telegram_token and len(telegram_token) > 10
            else "***" if telegram_token
            else None
        )

        forwarder_url = forwarder_cfg.get("url")
        forwarder_url_masked = (
            forwarder_url[:30] + "***" if forwarder_url and len(forwarder_url) > 30
            else forwarder_url if forwarder_url
            else None
        )

        glitchtip_dsn = glitchtip_cfg.get("dsn")
        glitchtip_dsn_masked = (
            glitchtip_dsn[:50] + "***" if glitchtip_dsn and len(glitchtip_dsn) > 50
            else glitchtip_dsn if glitchtip_dsn
            else None
        )

        return {
            "telegram": {
                "enabled": telegram_cfg.get("enabled", False),
                "bot_token_masked": telegram_token_masked,
                "chat_id": telegram_cfg.get("chat_id"),
                "runtime_override": runtime_config.has_telegram_override(),
                "updated_at": telegram_cfg.get("updated_at")
            },
            "forwarder": {
                "enabled": forwarder_cfg.get("enabled", False),
                "url_masked": forwarder_url_masked,
                "runtime_override": runtime_config.has_forwarder_override(),
                "updated_at": forwarder_cfg.get("updated_at")
            },
            "glitchtip": {
                "enabled": glitchtip_cfg.get("enabled", False),
                "dsn_masked": glitchtip_dsn_masked,
                "updated_at": glitchtip_cfg.get("updated_at")
            }
        }
    except Exception as e:
        logger.error(f"Error getting config: {e}")
        return {
            "telegram": {"enabled": False, "error": str(e)},
            "forwarder": {"enabled": False, "error": str(e)},
            "glitchtip": {"enabled": False, "error": str(e)}
        }


@router.put("/config/telegram")
async def update_telegram_config(
    config: Dict[str, Any],
    _: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Update Telegram configuration.

    Saves to runtime_config.json and takes effect immediately.
    Changes persist across container restarts.

    Body:
        {
            "enabled": bool,
            "bot_token": str (optional),
            "chat_id": str (optional)
        }
    """
    try:
        enabled = config.get("enabled", False)
        bot_token = config.get("bot_token")
        chat_id = config.get("chat_id")

        # Update runtime config (saves to JSON file)
        runtime_config.update_telegram(
            enabled=enabled,
            bot_token=bot_token,
            chat_id=chat_id
        )

        return {
            "success": True,
            "message": "Telegram configuration updated and saved to config/runtime_config.json",
            "config": {
                "enabled": enabled,
                "bot_token_masked": bot_token[:10] + "***" if bot_token else None,
                "chat_id": chat_id
            }
        }
    except Exception as e:
        logger.error(f"Error updating Telegram config: {e}")
        return {
            "success": False,
            "message": f"Failed to update Telegram config: {str(e)}"
        }


@router.put("/config/forwarder")
async def update_forwarder_config(
    config: Dict[str, Any],
    _: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Update Forwarder configuration.

    Saves to runtime_config.json and takes effect immediately.
    Changes persist across container restarts.

    Body:
        {
            "enabled": bool,
            "url": str (optional)
        }
    """
    try:
        enabled = config.get("enabled", False)
        url = config.get("url")

        # Update runtime config (saves to JSON file)
        runtime_config.update_forwarder(
            enabled=enabled,
            url=url
        )

        return {
            "success": True,
            "message": "Forwarder configuration updated and saved to config/runtime_config.json",
            "config": {
                "enabled": enabled,
                "url_masked": url[:30] + "***" if url and len(url) > 30 else url
            }
        }
    except Exception as e:
        logger.error(f"Error updating Forwarder config: {e}")
        return {
            "success": False,
            "message": f"Failed to update Forwarder config: {str(e)}"
        }


@router.put("/config/glitchtip")
async def update_glitchtip_config(
    config: Dict[str, Any],
    _: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Update GlitchTip configuration.

    Saves to runtime_config.json. Note: Application restart required for changes to take effect.
    Changes persist across container restarts.

    Body:
        {
            "enabled": bool,
            "dsn": str (optional)
        }
    """
    try:
        enabled = config.get("enabled", False)
        dsn = config.get("dsn")

        # Update runtime config (saves to JSON file)
        runtime_config.update_glitchtip(
            enabled=enabled,
            dsn=dsn
        )

        return {
            "success": True,
            "message": "GlitchTip configuration updated and saved to config/runtime_config.json. Restart required for changes to take effect.",
            "config": {
                "enabled": enabled,
                "dsn_masked": dsn[:50] + "***" if dsn and len(dsn) > 50 else dsn
            }
        }
    except Exception as e:
        logger.error(f"Error updating GlitchTip config: {e}")
        return {
            "success": False,
            "message": f"Failed to update GlitchTip config: {str(e)}"
        }
