"""Processor API routes."""

import os
from fastapi import APIRouter, Request, Response
from shopee_api.core.logger import setup_logger
from shopee_worker.services.webhook_processor import WebhookProcessor

logger = setup_logger(__name__)
router = APIRouter()

# Global webhook processor (initialized in app.py on startup)
webhook_processor: WebhookProcessor = None


def set_webhook_processor(processor: WebhookProcessor):
    """Set the global webhook processor instance.

    Called by app.py during startup event.

    Args:
        processor: Initialized WebhookProcessor instance
    """
    global webhook_processor
    webhook_processor = processor


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
            "workers_stats": "/workers/stats"
        }
    }
