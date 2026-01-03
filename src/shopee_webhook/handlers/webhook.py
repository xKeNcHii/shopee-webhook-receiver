"""Webhook event handling."""

import json
from typing import Any, Dict, Optional

from shopee_webhook.core.logger import setup_logger
from shopee_webhook.integrations.telegram import send_webhook_to_telegram

logger = setup_logger(__name__)


async def handle_webhook_event(
    event_payload: Dict[str, Any],
    authorization_header: str | None = None,
    order_service: Optional[Any] = None,
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

    # Log event
    try:
        from shopee_webhook.core.event_logger import log_webhook_event

        log_webhook_event(
            event_code=event_code,
            shop_id=shop_id,
            event_data=event_data,
            authorization_header=authorization_header,
            raw_body=json.dumps(event_payload),
        )
    except Exception as e:
        logger.error(f"Error logging webhook event: {e}")

    # Process order webhooks (Code 3 & 4)
    order_update_info = None
    if order_service and event_code in [3, 4]:
        try:
            logger.info(f"Processing order webhook (code={event_code}) with OrderService")
            order_update_info = await order_service.process_order_webhook(event_code, event_data)
        except Exception as e:
            logger.error(f"Error processing order webhook: {e}", exc_info=True)
            # Don't raise - webhook responses must still return 200 OK to Shopee

    # Send to Telegram (enhanced with order update info for better formatting)
    try:
        send_webhook_to_telegram(
            event_code=event_code,
            shop_id=shop_id,
            event_data=event_data,
            order_update_info=order_update_info,
        )
    except Exception as e:
        logger.error(f"Error sending webhook to Telegram: {e}")

    # Special handling for shipping documents (Code 15 & 25)
    if event_code in [15, 25]:
        try:
            from shopee_webhook.handlers.shipping import handle_shipping_document_ready
            from shopee_webhook.integrations.telegram import get_notifier

            order_sn = event_data.get("ordersn")
            package_number = event_data.get("package_number")
            booking_sn = event_data.get("booking_sn")

            if event_code == 15 and order_sn and package_number:
                handle_shipping_document_ready(
                    order_sn=order_sn,
                    package_number=package_number,
                    event_data=event_data,
                    telegram_notifier=get_notifier(),
                )
            elif event_code == 25 and booking_sn:
                logger.info(f"Booking shipping document ready for booking_sn: {booking_sn}")

        except Exception as e:
            logger.error(f"Error handling shipping document: {e}")
