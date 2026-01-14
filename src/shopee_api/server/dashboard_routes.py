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


@router.get("/dlq/stats")
async def get_dlq_stats(_: bool = Depends(verify_api_key)) -> Dict[str, Any]:
    """
    Get Dead Letter Queue statistics.

    Returns:
        - DLQ message count
        - Total enqueued, processed, failed counts
        - Sample of failed orders
    """
    try:
        from shopee_api.config.settings import settings
        import redis.asyncio as redis
        import json

        if not settings.redis_enabled:
            return {
                "enabled": False,
                "dlq_count": 0,
                "message": "Redis queue is disabled"
            }

        # Connect to Redis
        r = await redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True
        )

        # Get queue statistics
        dlq_count = await r.llen("shopee:webhooks:dead_letter")
        stats_raw = await r.hgetall("shopee:webhooks:stats")

        # Get sample messages from DLQ (first 5)
        sample_messages = []
        dlq_messages = await r.lrange("shopee:webhooks:dead_letter", 0, 4)

        for msg_json in dlq_messages:
            try:
                msg = json.loads(msg_json)
                payload = msg.get("payload", {})
                data = payload.get("data", {})
                metadata = msg.get("metadata", {})

                sample_messages.append({
                    "order_sn": data.get("ordersn", "unknown"),
                    "status": data.get("status", "unknown"),
                    "event_code": payload.get("code"),
                    "enqueued_at": metadata.get("enqueued_at"),
                    "moved_to_dlq_at": metadata.get("moved_to_dlq_at"),
                    "worker_id": metadata.get("worker_id")
                })
            except Exception:
                continue

        await r.aclose()

        return {
            "enabled": True,
            "dlq_count": dlq_count,
            "total_enqueued": int(stats_raw.get("total_enqueued", 0)),
            "total_processed": int(stats_raw.get("total_processed", 0)),
            "total_failed": int(stats_raw.get("total_failed", 0)),
            "sample_messages": sample_messages
        }

    except Exception as e:
        logger.error(f"Error getting DLQ stats: {e}", exc_info=True)
        return {
            "enabled": False,
            "dlq_count": 0,
            "error": str(e)
        }


@router.get("/dlq/messages")
async def get_dlq_messages(
    limit: int = Query(default=100, ge=1, le=500, description="Max messages to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    _: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get messages from Dead Letter Queue with pagination.

    Returns detailed list of failed orders for inspection.
    """
    try:
        from shopee_api.config.settings import settings
        import redis.asyncio as redis
        import json

        if not settings.redis_enabled:
            return {
                "enabled": False,
                "total": 0,
                "messages": []
            }

        # Connect to Redis
        r = await redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True
        )

        # Get total count
        total = await r.llen("shopee:webhooks:dead_letter")

        # Get paginated messages
        messages = []
        dlq_messages = await r.lrange("shopee:webhooks:dead_letter", offset, offset + limit - 1)

        for msg_json in dlq_messages:
            try:
                msg = json.loads(msg_json)
                payload = msg.get("payload", {})
                data = payload.get("data", {})
                metadata = msg.get("metadata", {})

                messages.append({
                    "order_sn": data.get("ordersn", "unknown"),
                    "status": data.get("status", "unknown"),
                    "event_code": payload.get("code"),
                    "shop_id": payload.get("shop_id"),
                    "timestamp": payload.get("timestamp"),
                    "enqueued_at": metadata.get("enqueued_at"),
                    "moved_to_dlq_at": metadata.get("moved_to_dlq_at"),
                    "retry_count": metadata.get("retry_count", 0),
                    "max_retries": metadata.get("max_retries", 3),
                    "worker_id": metadata.get("worker_id"),
                    "full_message": msg  # Include full message for retry
                })
            except Exception as e:
                logger.warning(f"Error parsing DLQ message: {e}")
                continue

        await r.aclose()

        return {
            "enabled": True,
            "total": total,
            "limit": limit,
            "offset": offset,
            "messages": messages
        }

    except Exception as e:
        logger.error(f"Error getting DLQ messages: {e}", exc_info=True)
        return {
            "enabled": False,
            "total": 0,
            "messages": [],
            "error": str(e)
        }


@router.post("/dlq/retry")
async def retry_dlq_messages(
    _: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Retry all messages from Dead Letter Queue.

    Moves all messages from DLQ back to main queue with reset metadata.
    """
    try:
        from shopee_api.config.settings import settings
        import redis.asyncio as redis
        import json
        import time

        if not settings.redis_enabled:
            return {
                "success": False,
                "message": "Redis queue is disabled"
            }

        # Connect to Redis
        r = await redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True
        )

        dlq_key = "shopee:webhooks:dead_letter"
        main_queue_key = "shopee:webhooks:main"

        # Get DLQ length
        dlq_length = await r.llen(dlq_key)

        if dlq_length == 0:
            await r.aclose()
            return {
                "success": True,
                "message": "No messages to retry",
                "retried_count": 0
            }

        # Move messages from DLQ to main queue
        retried = 0
        failed = 0

        while True:
            # Pop from DLQ (right side, oldest first)
            msg_json = await r.rpop(dlq_key)
            if not msg_json:
                break

            try:
                msg = json.loads(msg_json)

                # Reset metadata for retry
                msg["metadata"]["retry_count"] = 0
                msg["metadata"]["enqueued_at"] = time.time()
                msg["metadata"].pop("moved_to_dlq_at", None)
                msg["metadata"].pop("worker_id", None)

                # Re-enqueue to main queue (left side, same as original enqueue)
                new_msg_json = json.dumps(msg)
                await r.lpush(main_queue_key, new_msg_json)

                retried += 1

            except Exception as e:
                logger.error(f"Error retrying DLQ message: {e}")
                failed += 1

        await r.aclose()

        logger.info(f"DLQ retry completed: {retried} retried, {failed} failed")

        return {
            "success": True,
            "message": f"Successfully retried {retried} messages from DLQ",
            "retried_count": retried,
            "failed_count": failed
        }

    except Exception as e:
        logger.error(f"Error retrying DLQ: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Error retrying DLQ: {str(e)}",
            "retried_count": 0
        }


@router.post("/dlq/reset-stats")
async def reset_dlq_stats(
    _: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Reset queue statistics (total_enqueued, total_processed, total_failed).

    Does NOT affect DLQ messages - only resets the counters.
    """
    try:
        from shopee_api.config.settings import settings
        import redis.asyncio as redis

        if not settings.redis_enabled:
            return {
                "success": False,
                "message": "Redis queue is disabled"
            }

        r = await redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True
        )

        # Delete the stats hash
        await r.delete("shopee:webhooks:stats")
        await r.aclose()

        logger.info("Queue stats reset")

        return {
            "success": True,
            "message": "Queue statistics reset to zero"
        }

    except Exception as e:
        logger.error(f"Error resetting stats: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Error resetting stats: {str(e)}"
        }


@router.delete("/dlq/clear")
async def clear_dlq(
    _: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Clear all messages from Dead Letter Queue without retrying.

    WARNING: This permanently deletes all failed messages!
    """
    try:
        from shopee_api.config.settings import settings
        import redis.asyncio as redis

        if not settings.redis_enabled:
            return {
                "success": False,
                "message": "Redis queue is disabled"
            }

        # Connect to Redis
        r = await redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True
        )

        dlq_key = "shopee:webhooks:dead_letter"

        # Get count before deleting
        dlq_length = await r.llen(dlq_key)

        if dlq_length == 0:
            await r.aclose()
            return {
                "success": True,
                "message": "DLQ is already empty",
                "cleared_count": 0
            }

        # Delete the entire DLQ
        await r.delete(dlq_key)
        await r.aclose()

        logger.warning(f"DLQ cleared: {dlq_length} messages permanently deleted")

        return {
            "success": True,
            "message": f"Successfully cleared {dlq_length} messages from DLQ",
            "cleared_count": dlq_length
        }

    except Exception as e:
        logger.error(f"Error clearing DLQ: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Error clearing DLQ: {str(e)}",
            "cleared_count": 0
        }
