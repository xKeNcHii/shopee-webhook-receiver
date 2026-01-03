"""Pydantic models for order data."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EscrowItemSchema(BaseModel):
    """Single item in escrow/order_income data."""

    item_name: Optional[str] = None
    item_sku: Optional[str] = None
    model_name: Optional[str] = None
    model_sku: Optional[str] = None
    quantity_purchased: Optional[int] = None
    selling_price: Optional[float] = None

    class Config:
        extra = "allow"


class OrderIncomeSchema(BaseModel):
    """Order income/escrow data from Shopee API."""

    escrow_amount_after_adjustment: Optional[float] = None
    items: Optional[List[EscrowItemSchema]] = None

    class Config:
        extra = "allow"


class OrderItemSchema(BaseModel):
    """Order item from API."""

    item_name: Optional[str] = None
    item_sku: Optional[str] = None
    item_id: int
    model_id: int
    model_name: Optional[str] = None
    model_sku: Optional[str] = None
    model_quantity_purchased: int = 1
    model_discounted_price: float

    class Config:
        extra = "allow"


class RecipientAddressSchema(BaseModel):
    """Recipient address from order."""

    name: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    full_address: Optional[str] = None

    class Config:
        extra = "allow"


class OrderDetailResponse(BaseModel):
    """Order response from API."""

    order_sn: str
    shop_id: Optional[int] = None
    buyer_username: Optional[str] = None
    order_status: str
    create_time: int
    update_time: int
    total_amount: Optional[float] = None
    item_list: List[OrderItemSchema] = Field(default_factory=list)
    order_income: Optional[OrderIncomeSchema] = None
    recipient_address: Optional[RecipientAddressSchema] = None
    currency: Optional[str] = None
    payment_method: Optional[str] = None
    shipping_carrier: Optional[str] = None

    class Config:
        extra = "allow"


class OrderItemCreate(BaseModel):
    """Data for creating an OrderItem database record."""

    order_id: str
    date_time: datetime
    buyer: Optional[str] = None
    platform: str = "Shopee"
    product_name: Optional[str] = None
    item_type: Optional[str] = None
    parent_sku: Optional[str] = None
    sku: Optional[str] = None
    quantity: int = 1
    total_sale: Optional[float] = None
    shopee_status: Optional[str] = None
    status: str = ""

    class Config:
        from_attributes = True


class OrderItemInDB(OrderItemCreate):
    """Order item as stored in database."""

    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
