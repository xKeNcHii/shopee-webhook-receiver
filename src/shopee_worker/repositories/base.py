"""Abstract base repository for order storage."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class OrderRepository(ABC):
    """Abstract repository for order storage.

    This allows easy swapping between storage backends
    (Google Sheets, PostgreSQL, etc.)
    """

    @abstractmethod
    async def upsert_order_items(self, items: List[Dict[str, Any]]) -> bool:
        """Insert or update order items.

        Items are identified by Order ID + SKU combination.
        If an item exists, update it. Otherwise, insert new row.

        Args:
            items: List of order items with 12 columns:
                - order_id: Order serial number
                - date_time: Order creation timestamp
                - buyer: Buyer username
                - platform: "Shopee"
                - product_name: Item name
                - item_type: Model/variation name
                - parent_sku: Item SKU
                - sku: Model SKU
                - quantity: Quantity purchased
                - total_sale: Order total amount
                - shopee_status: Order status from Shopee
                - status: Order status (same as shopee_status)

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def get_order_items(self, order_id: str) -> List[Dict[str, Any]]:
        """Get all items for a specific order.

        Args:
            order_id: Order serial number

        Returns:
            List of order items matching the order_id
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if storage backend is accessible.

        Returns:
            True if healthy, False otherwise
        """
        pass
