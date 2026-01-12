"""Processor API routes."""

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


@router.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "service": "Shopee Order Processor",
        "description": "Processes Shopee webhooks and stores in Google Sheets",
        "endpoints": {
            "health": "/health",
            "webhook": "/webhook/process"
        }
    }
