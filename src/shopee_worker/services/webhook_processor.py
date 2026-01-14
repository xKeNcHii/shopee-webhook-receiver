"""Webhook processor business logic."""

import time
from typing import Dict, Any
from shopee_api.services.order_service import OrderService
from shopee_worker.repositories.base import OrderRepository
from shopee_api.core.logger import setup_logger
from shopee_api.core.monitoring import set_webhook_context
from shopee_api.config.constants import ORDER_EVENT_CODES, IGNORE_STATUSES

logger = setup_logger(__name__)


class WebhookProcessor:
    """Main business logic for processing webhooks.

    Business Rules:
    - Ignore UNPAID orders (don't add to Google Sheets)
    - Start from READY_TO_SHIP (first insertion)
    - Upsert on status changes (READY_TO_SHIP → PROCESSED → SHIPPED, etc.)
    - One row per item (multiple items = multiple rows)
    - Fetch full order details from Shopee API
    """

    def __init__(
        self,
        order_service: OrderService,
        repository: OrderRepository
    ):
        """Initialize webhook processor.

        Args:
            order_service: Service for fetching order data from Shopee API
            repository: Storage repository (Google Sheets, PostgreSQL, etc.)
        """
        self.order_service = order_service
        self.repository = repository

    async def process_webhook(self, event_payload: Dict[str, Any]) -> bool:
        """Process incoming webhook event.

        Business Logic:
        1. Extract order_sn and status from event
        2. If status is UNPAID, ignore
        3. If event code is 3 or 4 (order events), fetch full order
        4. Parse items to 12-column format
        5. Upsert items to repository

        Args:
            event_payload: Raw webhook from forwarder
                Example: {
                    "code": 3,
                    "shop_id": 443972786,
                    "timestamp": 1704337899,
                    "data": {
                        "ordersn": "2601033YS140TT",
                        "status": "READY_TO_SHIP"
                    }
                }

        Returns:
            True if processed successfully
        """
        try:
            start_time = time.time()
            event_code = event_payload.get("code")
            shop_id = event_payload.get("shop_id")
            event_data = event_payload.get("data", {})
            order_sn = event_data.get("ordersn")
            status = event_data.get("status")

            # Set error monitoring context
            set_webhook_context(
                event_code=event_code,
                shop_id=shop_id,
                order_sn=order_sn
            )

            logger.info(
                f"Processing webhook: code={event_code}, "
                f"order={order_sn}, status={status}"
            )

            # Business Rule 1: Ignore UNPAID orders
            if status in IGNORE_STATUSES:
                logger.info(f"Ignoring {status} order {order_sn}")
                return True

            # Business Rule 2: Only process order events (code 3 = status update, 4 = tracking)
            if event_code not in ORDER_EVENT_CODES:
                logger.info(f"Skipping non-order event (code={event_code})")
                return True

            if not order_sn:
                logger.warning("No order_sn in webhook data")
                return False

            # Fetch full order details from Shopee API
            logger.info(f"Fetching order details for {order_sn}")
            
            t0 = time.time()
            order_info = await self.order_service.fetch_order_details(order_sn)
            t1 = time.time()
            logger.info(f"[TIMER] Shopee API Fetch: {t1 - t0:.2f}s")

            if not order_info:
                logger.error(f"Failed to fetch order {order_sn}")
                return False

            # Extract parsed items from order_data
            order_data = order_info.get("order_data", {})
            items = order_data.get("items", [])

            if not items:
                logger.warning(f"No items found for order {order_sn}")
                return True

            # Check if order should be added (based on current API status, not webhook status)
            current_status = items[0].get("shopee_status", status) if items else status

            if current_status in IGNORE_STATUSES:
                logger.info(f"Order {order_sn} is {current_status}, skipping")
                return True

            # Upsert items to storage
            logger.info(f"Upserting {len(items)} items for order {order_sn}")
            
            t2 = time.time()
            success = await self.repository.upsert_order_items(items)
            t3 = time.time()
            logger.info(f"[TIMER] Google Sheets Upsert: {t3 - t2:.2f}s")

            if success:
                logger.info(f"Successfully processed order {order_sn}")
            else:
                logger.error(f"Failed to upsert order {order_sn}")

            total_duration = time.time() - start_time
            logger.info(f"[TIMER] Total Processing Time: {total_duration:.2f}s")
            
            return success

        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
            return False
