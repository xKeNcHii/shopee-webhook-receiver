"""Order service for fetching and formatting order data."""

from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from shopee_webhook.api.client import ShopeeAPIClient
from shopee_webhook.core.logger import setup_logger
from shopee_webhook.models.order import OrderDetailResponse

logger = setup_logger(__name__)


class OrderUpdateInfo(TypedDict, total=False):
    """Information about an order for forwarding and Telegram notification."""

    order_data: Dict[str, Any]  # Full order data


class OrderService:
    """Fetches and formats order data from Shopee API."""

    def __init__(self, api_client: ShopeeAPIClient):
        """Initialize service with API client."""
        self.api_client = api_client

    async def process_order_webhook(
        self,
        event_code: int,
        event_data: dict,
    ) -> Optional[OrderUpdateInfo]:
        """
        Process an order webhook by fetching order details from API.

        Args:
            event_code: Webhook event code (3 for status, 4 for tracking)
            event_data: Webhook event data containing order info

        Returns:
            OrderUpdateInfo with order details, or None on error
        """
        try:
            # Extract order SN from event data
            order_sn = event_data.get("ordersn") or event_data.get("order_sn")

            if not order_sn:
                logger.warning(f"No order SN in webhook event data: {event_data}")
                return None

            logger.info(f"Processing webhook for order {order_sn} (code={event_code})")

            # Fetch order details
            order_info = await self.fetch_order_details(order_sn)
            return order_info

        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
            return None

    async def fetch_order_details(
        self,
        order_sn: str,
    ) -> Optional[OrderUpdateInfo]:
        """
        Fetch order details from Shopee API and format for forwarding.

        Args:
            order_sn: Shopee order SN

        Returns:
            OrderUpdateInfo with formatted order data, or None on error
        """
        try:
            logger.info(f"Fetching order details from API for {order_sn}")

            # Call Shopee API to get order details
            api_response = await self.api_client.get_order_detail([order_sn])

            # Parse response
            order_list = api_response.get("response", {}).get("order_list", [])

            if not order_list:
                logger.warning(f"No orders found in API response for {order_sn}")
                return None

            # Process first order (we only requested one)
            order_data = order_list[0]
            order_detail = OrderDetailResponse(**order_data)

            logger.info(
                f"Got order {order_detail.order_sn} with {len(order_detail.item_list)} items"
            )

            # Format order data for forwarding and Telegram
            items_data = self._parse_order_items(order_detail)
            order_data_formatted = self._format_order_details(order_detail, items_data)

            return OrderUpdateInfo(
                order_data=order_data_formatted,
            )

        except Exception as e:
            logger.error(f"Error fetching order {order_sn}: {e}", exc_info=True)
            return None

    def _format_order_details(
        self,
        order: OrderDetailResponse,
        items_data: List[dict],
    ) -> Dict[str, Any]:
        """
        Format full order details for forwarding and Telegram notification.
        Includes all available data from API response.

        Args:
            order: OrderDetailResponse from API
            items_data: List of parsed items

        Returns:
            Dictionary with all order details
        """
        # Build recipient address details if available
        recipient_address = {}
        if order.recipient_address:
            recipient_address = {
                "name": order.recipient_address.name,
                "phone": order.recipient_address.phone,
                "city": order.recipient_address.city,
                "district": order.recipient_address.district,
                "state": order.recipient_address.state,
                "full_address": order.recipient_address.full_address,
            }

        # Build order income/escrow details if available
        order_income_details = {}
        if order.order_income:
            order_income_details = {
                "escrow_amount_after_adjustment": order.order_income.escrow_amount_after_adjustment,
                "escrow_items": order.order_income.items,
            }

        return {
            # Basic order info
            "order_id": order.order_sn,
            "shop_id": order.shop_id,
            "buyer": order.buyer_username,
            "platform": "Shopee",
            "status": order.order_status,
            "create_time": datetime.utcfromtimestamp(order.create_time).isoformat(),
            "update_time": datetime.utcfromtimestamp(order.update_time).isoformat(),
            # Financial info
            "total_amount": order.total_amount,
            "currency": order.currency,
            # Shipping and payment info
            "payment_method": order.payment_method,
            "shipping_carrier": order.shipping_carrier,
            # Items
            "item_count": len(items_data),
            "items": items_data,
            # Recipient address
            "recipient_address": recipient_address,
            # Order income (escrow)
            "order_income": order_income_details,
        }

    def _parse_order_items(
        self,
        order: OrderDetailResponse,
    ) -> List[dict]:
        """
        Parse Shopee API order response into list of items.

        Args:
            order: Parsed OrderDetailResponse from API

        Returns:
            List of dicts with item details
        """
        order_datetime = datetime.utcfromtimestamp(order.create_time).isoformat()
        source_items = order.item_list

        # Parse each item
        items = []
        for item in source_items:
            # Determine SKU
            sku = (
                (item.model_sku or item.item_sku or "").strip()
                if hasattr(item, "model_sku")
                else (item.get("model_sku") or item.get("item_sku") or "").strip()
            )
            if not sku:
                item_name = (
                    item.item_name
                    if hasattr(item, "item_name")
                    else item.get("item_name", "UNKNOWN_ITEM")
                )
                sku = f"NO_SKU_{item_name}".strip()

            qty = item.model_quantity_purchased or 1

            item_dict = {
                "order_id": order.order_sn,
                "date_time": order_datetime,
                "buyer": order.buyer_username or "",
                "platform": "Shopee",
                "product_name": item.item_name or "",
                "item_type": item.model_name or "",
                "parent_sku": item.item_sku or "",
                "sku": sku,
                "quantity": qty,
                "total_sale": order.total_amount,
                "shopee_status": order.order_status,
                "status": order.order_status,
            }
            items.append(item_dict)

        logger.info(f"Parsed {len(items)} items for order {order.order_sn}")
        return items
