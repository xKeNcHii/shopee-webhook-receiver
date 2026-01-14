"""Webhook event handling."""

import json
from datetime import datetime
from typing import Any, Dict, Optional

from shopee_api.core.logger import setup_logger
from shopee_api.integrations.telegram import send_webhook_to_telegram
from shopee_api.integrations.forwarder import WebhookForwarder
from shopee_api.config.constants import ORDER_EVENT_CODES

logger = setup_logger(__name__)


async def handle_webhook_event(
    event_payload: Dict[str, Any],
    authorization_header: str | None = None,
    order_service: Optional[Any] = None,
    forwarder: Optional[WebhookForwarder] = None,
) -> None:
    """
    Handle incoming webhook event.

    Args:
        event_payload: Parsed webhook event payload
        authorization_header: Authorization header value
        order_service: Optional OrderService for database operations
    """
    event_code = event_payload.get("code")
    shop_id = event_payload.get("shop_id")
    event_data = event_payload.get("data", {})

    logger.info(f"Processing webhook: code={event_code}, shop_id={shop_id}")

    # Set error monitoring context for this webhook
    try:
        from shopee_api.core.monitoring import set_webhook_context
        order_sn = event_data.get("ordersn")
        set_webhook_context(
            event_code=event_code,
            shop_id=shop_id,
            order_sn=order_sn
        )
    except Exception:
        pass  # Don't fail webhook processing if monitoring fails

    # Process order webhooks (Code 3 & 4)
    order_update_info = None
    if order_service and event_code in ORDER_EVENT_CODES:
        try:
            logger.info(f"Processing order webhook (code={event_code}) with OrderService")
            order_update_info = await order_service.process_order_webhook(event_code, event_data)
        except Exception as e:
            logger.error(f"Error processing order webhook: {e}", exc_info=True)
            # Don't raise - webhook responses must still return 200 OK to Shopee

    # Initialize processing status tracking for dashboard
    telegram_result = {"success": False, "error": None, "timestamp": None}
    forwarder_result = {"success": False, "error": None, "timestamp": None}

    # Send to Telegram (enhanced with order update info for better formatting)
    try:
        telegram_success = send_webhook_to_telegram(
            event_code=event_code,
            shop_id=shop_id,
            event_data=event_data,
            order_update_info=order_update_info,
        )
        if telegram_success:
            telegram_result = {
                "success": True,
                "error": None,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            # Check if Telegram is configured
            from shopee_api.integrations.telegram import get_notifier
            notifier = get_notifier()
            if not notifier.enabled:
                error_msg = "Telegram not configured"
            else:
                error_msg = "Send failed (check Telegram logs)"

            telegram_result = {
                "success": False,
                "error": error_msg,
                "timestamp": datetime.utcnow().isoformat()
            }
    except Exception as e:
        logger.error(f"Error sending webhook to Telegram: {e}")
        telegram_result = {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

    # Initialize Redis queue for forwarder (if enabled)
    # This is done here instead of at module level to support runtime config changes
    if forwarder:
        try:
            from shopee_api.config.settings import settings
            if settings.redis_enabled and not forwarder.redis_queue:
                from shopee_api.integrations.redis_queue import get_redis_queue
                forwarder.redis_queue = get_redis_queue()
                logger.debug("Redis queue attached to forwarder")
        except Exception as e:
            logger.warning(f"Failed to initialize Redis queue for forwarder: {e}")
            # Continue without Redis - forwarder will use HTTP fallback

    # Forward to custom service (if configured)
    # Only forward the raw webhook event - processor can fetch order details if needed
    if forwarder:
        try:
            forward_result = await forwarder.forward_webhook(
                event_payload=event_payload,
            )
            
            # Unpack result dict
            success = forward_result.get("success", False)
            attempts = forward_result.get("attempts", 0)
            last_error = forward_result.get("last_error")

            forwarder_result = {
                "success": success,
                "error": last_error if not success else None,
                "attempts": attempts,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error forwarding webhook: {e}")
            forwarder_result = {
                "success": False,
                "error": str(e),
                "attempts": 0,
                "timestamp": datetime.utcnow().isoformat()
            }

    # Log processing status for dashboard monitoring
    try:
        from shopee_api.core.event_logger import log_webhook_event

        log_webhook_event(
            event_code=event_code,
            shop_id=shop_id,
            event_data=event_data,
            authorization_header=authorization_header,
            raw_body=json.dumps(event_payload),
            processing_status={
                "telegram": telegram_result,
                "forwarder": forwarder_result
            }
        )
    except Exception as e:
        logger.error(f"Error logging processing status: {e}")
