"""SQLAlchemy models for order data."""

from datetime import datetime

from sqlalchemy import Column, Float, Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OrderItem(Base):
    """
    Represents a single item from a Shopee order.

    Each order can have multiple items. This table denormalizes order-level fields
    across all items so we have one row per item.
    """

    __tablename__ = "order_items"

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Order-level fields (duplicated across all items of same order)
    order_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    date_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    buyer: Mapped[str] = mapped_column(String(255), nullable=True)
    platform: Mapped[str] = mapped_column(String(50), default="Shopee", nullable=False)

    # Item-level fields
    product_name: Mapped[str] = mapped_column(String(500), nullable=True)
    item_type: Mapped[str] = mapped_column(String(255), nullable=True)
    parent_sku: Mapped[str] = mapped_column(String(100), nullable=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    total_sale: Mapped[float] = mapped_column(Float, nullable=True)

    # Order status fields
    shopee_status: Mapped[str] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(100), default="", nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
