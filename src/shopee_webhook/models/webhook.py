"""Pydantic models for webhook events."""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class WebhookEvent(BaseModel):
    """Base webhook event structure from Shopee."""

    code: int = Field(..., description="Event code (3=order status, 4=tracking, etc.)")
    shop_id: int = Field(..., description="Shop ID")
    timestamp: int = Field(..., description="Unix timestamp of webhook")
    data: Optional[dict] = Field(None, description="Event-specific data")
    msg_id: Optional[str] = Field(None, description="Unique message ID")

    class Config:
        extra = "allow"


class OrderStatusUpdate(BaseModel):
    """Order status update webhook data (Code 3)."""

    ordersn: Optional[str] = Field(None, alias="ordersn", description="Order SN")
    order_sn: Optional[str] = Field(None, description="Order SN (alternative field)")
    status: Optional[str] = Field(None, description="New order status")
    update_time: Optional[int] = Field(None, description="Update timestamp")

    class Config:
        extra = "allow"
        populate_by_name = True

    def get_order_sn(self) -> Optional[str]:
        """Extract order SN from either field name."""
        return self.ordersn or self.order_sn


class OrderTrackingUpdate(BaseModel):
    """Tracking number update webhook data (Code 4)."""

    ordersn: Optional[str] = Field(None, alias="ordersn", description="Order SN")
    order_sn: Optional[str] = Field(None, description="Order SN (alternative field)")
    tracking_number: Optional[str] = Field(None, description="Tracking number")
    shipping_carrier: Optional[str] = Field(None, description="Logistics provider")
    update_time: Optional[int] = Field(None, description="Update timestamp")

    class Config:
        extra = "allow"
        populate_by_name = True

    def get_order_sn(self) -> Optional[str]:
        """Extract order SN from either field name."""
        return self.ordersn or self.order_sn
