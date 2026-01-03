"""Repository for order items data access."""

from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import OrderItem


class OrderItemRepository:
    """Data access layer for OrderItem model."""

    def __init__(self, session: AsyncSession):
        """Initialize repository with async session."""
        self.session = session

    async def get_by_order_id(self, order_id: str) -> List[OrderItem]:
        """Get all items for a specific order."""
        query = select(OrderItem).where(OrderItem.order_id == order_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def delete_by_order_id(self, order_id: str) -> int:
        """Delete all items for a specific order. Returns count of deleted rows."""
        stmt = delete(OrderItem).where(OrderItem.order_id == order_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount

    async def upsert_order_items(
        self, order_id: str, items_data: List[dict]
    ) -> List[OrderItem]:
        """
        Upsert order items by deleting existing and inserting new ones.

        Args:
            order_id: The order identifier
            items_data: List of dicts with item data to insert

        Returns:
            List of newly created OrderItem objects
        """
        # Delete existing items for this order
        await self.delete_by_order_id(order_id)

        # Create and insert new items
        new_items = [OrderItem(**item_data) for item_data in items_data]
        self.session.add_all(new_items)
        await self.session.commit()

        # Refresh to get all attributes (including IDs)
        for item in new_items:
            await self.session.refresh(item)

        return new_items
