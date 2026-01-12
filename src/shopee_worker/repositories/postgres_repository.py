"""PostgreSQL repository implementation (FUTURE - NOT IMPLEMENTED YET)."""

from typing import List, Dict, Any
from shopee_worker.repositories.base import OrderRepository


class PostgresRepository(OrderRepository):
    """PostgreSQL storage implementation.

    This is a stub for future implementation when migrating from Google Sheets
    to PostgreSQL database.

    To implement:
    1. Add SQLAlchemy dependencies to requirements.txt
    2. Create database schema (12-column table)
    3. Implement upsert using ON CONFLICT (order_id, sku) DO UPDATE
    4. Update app.py to conditionally create repository based on STORAGE_BACKEND env var
    """

    def __init__(self, db_session):
        """Initialize PostgreSQL repository.

        Args:
            db_session: SQLAlchemy async session
        """
        self.session = db_session

    async def upsert_order_items(self, items: List[Dict[str, Any]]) -> bool:
        """Insert or update order items using PostgreSQL UPSERT.

        NOT IMPLEMENTED YET - placeholder for future development.

        Example SQL:
            INSERT INTO order_items (order_id, sku, ...)
            VALUES (?, ?, ...)
            ON CONFLICT (order_id, sku)
            DO UPDATE SET
                status = EXCLUDED.status,
                shopee_status = EXCLUDED.shopee_status,
                ...
        """
        raise NotImplementedError(
            "PostgreSQL repository not implemented yet. "
            "Use GoogleSheetsRepository instead."
        )

    async def get_order_items(self, order_id: str) -> List[Dict[str, Any]]:
        """Get all items for an order.

        NOT IMPLEMENTED YET - placeholder for future development.
        """
        raise NotImplementedError(
            "PostgreSQL repository not implemented yet. "
            "Use GoogleSheetsRepository instead."
        )

    async def health_check(self) -> bool:
        """Check database connection.

        NOT IMPLEMENTED YET - placeholder for future development.
        """
        raise NotImplementedError(
            "PostgreSQL repository not implemented yet. "
            "Use GoogleSheetsRepository instead."
        )
