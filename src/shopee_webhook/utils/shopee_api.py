#!/usr/bin/env python3
"""
Shopee API Utilities

Provides helper functions for making authenticated API calls to Shopee.
"""

import hmac
import hashlib


def get_signed_url(path: str, timestamp: int, access_token: str, shop_id: int) -> str:
    """
    Generate HMAC-SHA256 signature for Shopee API requests.

    Args:
        path: API endpoint path (e.g., "/api/v2/order/get_order_list")
        timestamp: Unix timestamp
        access_token: Shopee access token
        shop_id: Shopee shop ID

    Returns:
        HMAC-SHA256 signature as hex string
    """
    from shopee_webhook.config.settings import settings

    # Build base string: PARTNER_ID + path + timestamp + access_token + shop_id
    base_string = f"{settings.partner_id}{path}{timestamp}{access_token}{shop_id}"

    # Generate HMAC-SHA256 signature
    signature = hmac.new(
        settings.partner_key.encode('utf-8'),
        base_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return signature
