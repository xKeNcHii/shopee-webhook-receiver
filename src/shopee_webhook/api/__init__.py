"""Shopee Open Platform API module."""

from .client import ShopeeAPIClient
from .endpoints import GET_ORDER_DETAIL

__all__ = ["ShopeeAPIClient", "GET_ORDER_DETAIL"]
