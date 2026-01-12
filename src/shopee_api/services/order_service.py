"""Order service for fetching and formatting order data."""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from shopee_api.api.client import ShopeeAPIClient
from shopee_api.core.logger import setup_logger
from shopee_api.models.order import OrderDetailResponse
from shopee_api.config.constants import CURRENCY_DECIMAL_PLACES

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

            # OPTIMIZATION: Parallelize Order API and Escrow API calls
            # Fetch both APIs concurrently instead of sequentially
            # Saves ~300ms by running in parallel instead of order→escrow
            api_response, escrow_data = await asyncio.gather(
                self.api_client.get_order_detail([order_sn]),
                self._fetch_escrow_data(order_sn),
                return_exceptions=True  # Don't fail entire operation if one API fails
            )

            # Handle if Order API failed
            if isinstance(api_response, Exception):
                logger.error(f"Order API failed: {api_response}")
                return None

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

            # Handle if Escrow API failed (non-fatal, we can fall back to order total)
            if isinstance(escrow_data, Exception):
                logger.warning(f"Escrow API failed (will use fallback): {escrow_data}")
                escrow_data = None

            # Format order data for forwarding and Telegram
            items_data = self._parse_order_items(order_detail, escrow_data)
            order_data_formatted = self._format_order_details(order_detail, items_data)

            return OrderUpdateInfo(
                order_data=order_data_formatted,
            )

        except Exception as e:
            logger.error(f"Error fetching order {order_sn}: {e}", exc_info=True)
            return None

    async def _fetch_escrow_data(self, order_sn: str) -> Optional[dict]:
        """
        Fetch escrow/settlement details from Payment API.

        This provides the actual wallet deposit amount (escrow_amount) and per-item
        breakdown for calculating net income.

        Args:
            order_sn: Shopee order SN

        Returns:
            Escrow data dict, or None if not available
        """
        try:
            logger.info(f"Fetching escrow data from Payment API for {order_sn}")
            escrow_response = await self.api_client.get_escrow_detail(order_sn)

            # Check if API returned an error
            if escrow_response.get("error"):
                logger.info(
                    f"Escrow data not available for {order_sn}: {escrow_response.get('message', 'Unknown error')} "
                    "(order may not be settled yet)"
                )
                return None

            logger.info(f"Escrow data fetched successfully for {order_sn}")
            return escrow_response

        except Exception as e:
            logger.warning(f"Could not fetch escrow data for {order_sn}: {e}")
            return None

    def _calculate_item_net_income(
        self,
        item: Any,
        escrow_data: Optional[dict],
    ) -> float:
        """
        Calculate net income for a single item using pro-rata distribution.

        LOGIC BLUEPRINT (from ecroww.py):
        1. The 'escrow_amount' is the ONLY ground truth - it's the actual wallet deposit
        2. We distribute this amount proportionally across items based on their price ratio
        3. This ensures our item-level accounting matches the bank statement exactly

        Args:
            item: OrderItemSchema from API
            escrow_data: Escrow response from Payment API

        Returns:
            Net income for this item (actual profit after all fees), or 0.0 if unavailable
        """
        if not escrow_data:
            logger.warning("Escrow data not available for net income calculation")
            return 0.0

        try:
            response = escrow_data.get("response", {})
            order_income = response.get("order_income", {})

            # THE ANCHOR: Actual cash deposited to wallet
            escrow_amount = order_income.get("escrow_amount", 0)

            if escrow_amount == 0:
                logger.debug("Escrow amount is 0")
                return 0.0

            # Get escrow items for proportional calculation
            escrow_items = order_income.get("items", [])

            if not escrow_items:
                logger.debug("No escrow items available")
                return 0.0

            # THE REVENUE BASE: Sum of all line items (gross merchandise value)
            # Note: In Escrow API, 'selling_price' is the line total (Price * Qty)
            total_merch_value = sum(ei.get("selling_price", 0) for ei in escrow_items)

            if total_merch_value == 0:
                logger.debug("Total merchandise value is 0")
                return 0.0

            # Find matching escrow item by SKU
            matching_escrow = None
            for escrow_item in escrow_items:
                if (escrow_item.get("model_sku") and escrow_item.get("model_sku") == item.model_sku) or \
                   (escrow_item.get("item_sku") and escrow_item.get("item_sku") == item.item_sku):
                    matching_escrow = escrow_item
                    break

            if not matching_escrow:
                logger.warning(
                    f"Could not match item {item.model_sku or item.item_sku} to escrow data"
                )
                return 0.0

            # PRO-RATA CALCULATION: Share payout based on item's contribution to revenue
            line_total = matching_escrow.get("selling_price", 0)
            ratio = line_total / total_merch_value
            item_net = escrow_amount * ratio

            logger.debug(
                f"Calculated net income for {item.model_sku or item.item_sku}: "
                f"${item_net:.2f} (ratio={ratio:.4f}, escrow_amount=${escrow_amount:.2f})"
            )

            return round(item_net, CURRENCY_DECIMAL_PLACES)

        except Exception as e:
            logger.error(f"Error calculating net income: {e}", exc_info=True)
            return 0.0

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
        escrow_data: Optional[dict] = None,
    ) -> List[dict]:
        """
        Parse Shopee API order response into list of items with net income calculation.

        Args:
            order: Parsed OrderDetailResponse from API
            escrow_data: Escrow data from Payment API (optional)

        Returns:
            List of dicts with item details including calculated net income
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

            # Calculate net income for this item using pro-rata distribution
            # This is the actual profit after all Shopee fees and adjustments
            net_income = self._calculate_item_net_income(
                item,
                escrow_data,
            )

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
                "total_sale": net_income,
                "shopee_status": order.order_status,
                "status": order.order_status,
            }
            items.append(item_dict)

        logger.info(f"Parsed {len(items)} items for order {order.order_sn}")
        return items
