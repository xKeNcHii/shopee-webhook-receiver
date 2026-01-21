"""Processor API routes."""

import os
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Optional
from fastapi import APIRouter, Request, Response, Query
from shopee_api.core.logger import setup_logger
from shopee_worker.services.webhook_processor import WebhookProcessor

logger = setup_logger(__name__)
router = APIRouter()

# Global instances (initialized in app.py on startup)
webhook_processor: WebhookProcessor = None
reconciliation_service = None
reconciliation_scheduler = None


def set_webhook_processor(processor: WebhookProcessor):
    """Set the global webhook processor instance.

    Called by app.py during startup event.

    Args:
        processor: Initialized WebhookProcessor instance
    """
    global webhook_processor
    webhook_processor = processor


def set_reconciliation_service(service):
    """Set the global reconciliation service instance."""
    global reconciliation_service
    reconciliation_service = service


def set_reconciliation_scheduler(scheduler):
    """Set the global reconciliation scheduler instance."""
    global reconciliation_scheduler
    reconciliation_scheduler = scheduler


@router.post("/webhook/process")
async def process_webhook(request: Request) -> Response:
    """Receive webhook from forwarder and process.

    Expected payload from forwarder:
    {
      "code": 3,
      "shop_id": 443972786,
      "timestamp": 1704337899,
      "data": {
        "ordersn": "2601033YS140TT",
        "status": "READY_TO_SHIP"
      }
    }

    Business Logic:
    - Ignore UNPAID orders
    - Fetch full order details from Shopee API
    - Parse to 12-column format
    - Upsert to Google Sheets (by Order ID + SKU)

    Returns:
        200 OK if processed successfully
        500 Internal Server Error if processing failed
    """
    try:
        event_payload = await request.json()

        if not webhook_processor:
            logger.error("Webhook processor not initialized")
            return Response(status_code=500, content="Processor not initialized")

        logger.info(f"Received webhook: code={event_payload.get('code')}")

        success = await webhook_processor.process_webhook(event_payload)

        if success:
            return Response(status_code=200)
        else:
            return Response(status_code=500, content="Processing failed")

    except Exception as e:
        logger.error(f"Error in webhook endpoint: {e}", exc_info=True)
        return Response(status_code=500, content=str(e))


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint.

    Checks:
    - Processor initialization
    - Storage backend accessibility

    Returns:
        {
            "status": "healthy|degraded|unhealthy",
            "service": "shopee-order-processor",
            "storage": "ok|error"
        }
    """
    if not webhook_processor:
        return {
            "status": "unhealthy",
            "service": "shopee-order-processor",
            "error": "Processor not initialized"
        }

    # Check storage backend
    try:
        storage_ok = await webhook_processor.repository.health_check()
    except Exception as e:
        logger.error(f"Health check error: {e}")
        storage_ok = False

    return {
        "status": "healthy" if storage_ok else "degraded",
        "service": "shopee-order-processor",
        "storage": "ok" if storage_ok else "error"
    }


@router.get("/workers/stats")
async def worker_stats(request: Request) -> dict:
    """Get Redis worker statistics for monitoring.

    Returns statistics for all active Redis consumer workers:
    - Worker ID and status
    - Messages processed/failed counts
    - Current message being processed
    - Average processing time

    Returns:
        {
            "redis_enabled": bool,
            "total_workers": int,
            "workers": [
                {
                    "worker_id": int,
                    "is_running": bool,
                    "current_message": str | None,
                    "messages_processed": int,
                    "messages_failed": int,
                    "avg_processing_time": float,
                    "last_message_at": float | None
                },
                ...
            ]
        }
    """
    try:
        redis_enabled = os.getenv("REDIS_ENABLED", "true").lower() == "true"

        if not redis_enabled:
            return {
                "redis_enabled": False,
                "message": "Redis workers not enabled"
            }

        # Get worker tasks from app state
        if not hasattr(request.app.state, "worker_tasks"):
            return {
                "redis_enabled": True,
                "error": "Worker tasks not initialized"
            }

        worker_tasks = request.app.state.worker_tasks

        if not worker_tasks:
            return {
                "redis_enabled": True,
                "error": "No workers running"
            }

        # Collect stats from all workers
        workers_info = []
        for consumer, task in worker_tasks:
            stats = consumer.get_stats()
            workers_info.append(stats)

        return {
            "redis_enabled": True,
            "total_workers": len(workers_info),
            "workers": workers_info
        }

    except Exception as e:
        logger.error(f"Error getting worker stats: {e}", exc_info=True)
        return {
            "error": str(e),
            "redis_enabled": redis_enabled if 'redis_enabled' in locals() else False
        }


@router.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "service": "Shopee Order Processor",
        "description": "Processes Shopee webhooks and stores in Google Sheets",
        "endpoints": {
            "health": "/health",
            "webhook": "/webhook/process",
            "workers_stats": "/workers/stats",
            "reconciliation_status": "/api/reconciliation/status",
            "reconciliation_sync": "/api/reconciliation/sync",
            "reconciliation_history": "/api/reconciliation/history"
        }
    }


# ==============================================================================
# RECONCILIATION ENDPOINTS
# ==============================================================================

@router.get("/api/reconciliation/status")
async def get_reconciliation_status() -> dict:
    """Get current reconciliation status for dashboard.

    Returns:
        - last_sync_timestamp
        - last_full_sync_timestamp
        - next_scheduled_sync
        - sync_in_progress
        - sync_history (last 10 syncs)
    """
    if not reconciliation_service:
        return {
            "success": False,
            "error": "Reconciliation service not initialized"
        }

    try:
        # Get next scheduled sync time from scheduler
        next_scheduled = None
        if reconciliation_scheduler:
            next_scheduled = reconciliation_scheduler.get_next_scheduled_sync()

        status = await reconciliation_service.get_sync_status(next_scheduled)

        return {
            "success": True,
            "status": asdict(status)
        }

    except Exception as e:
        logger.error(f"Error getting reconciliation status: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/api/reconciliation/sync")
async def trigger_manual_sync(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
) -> dict:
    """Trigger manual reconciliation for date range.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Sync result with orders_fetched, orders_processed, errors
    """
    if not reconciliation_service:
        return {
            "success": False,
            "error": "Reconciliation service not initialized"
        }

    try:
        # Parse dates
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

        # Run manual sync
        result = await reconciliation_service.manual_sync(start, end)

        return {
            "success": result.success,
            "result": asdict(result)
        }

    except ValueError as e:
        return {
            "success": False,
            "error": f"Invalid date format: {e}"
        }
    except Exception as e:
        logger.error(f"Error in manual sync: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/api/reconciliation/history")
async def get_sync_history(
    limit: int = Query(10, ge=1, le=50, description="Number of history entries")
) -> dict:
    """Get sync history.

    Args:
        limit: Maximum number of history entries to return

    Returns:
        List of recent sync results
    """
    if not reconciliation_service:
        return {
            "success": False,
            "error": "Reconciliation service not initialized"
        }

    try:
        status = await reconciliation_service.get_sync_status()

        return {
            "success": True,
            "history": status.sync_history[:limit]
        }

    except Exception as e:
        logger.error(f"Error getting sync history: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }
