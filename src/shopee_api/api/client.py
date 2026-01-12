"""Shopee Open Platform API client."""

import hashlib
import hmac
import time
from typing import List, Optional

import httpx

from shopee_api.core.logger import setup_logger
from shopee_api.core.token_manager import load_tokens, save_tokens, is_token_expired
from .endpoints import GET_ORDER_DETAIL

logger = setup_logger(__name__)

# Token expiration default (Shopee API default)
TOKEN_EXPIRATION_DEFAULT = 7200


class ShopeeAPIClient:
    """Async HTTP client for Shopee Open Platform API."""

    def __init__(
        self,
        partner_id: int,
        partner_key: str,
        shop_id: int,
        access_token: str,
        refresh_token: Optional[str] = None,
        host_api: str = "https://partner.shopeemobile.com",
    ):
        """Initialize API client with credentials."""
        self.partner_id = partner_id
        self.partner_key = partner_key
        self.shop_id = shop_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.host_api = host_api
        self.client = httpx.AsyncClient(timeout=30.0)

        # Try to load tokens from storage (for refresh capability)
        stored_tokens = load_tokens()
        if stored_tokens:
            self.access_token = stored_tokens.get("access_token", access_token)
            self.refresh_token = stored_tokens.get("refresh_token", refresh_token)
            logger.info("Loaded tokens from storage")
        else:
            # Initialize with .env tokens - set expiration to now (will trigger refresh immediately if needed)
            save_tokens({
                "access_token": access_token,
                "refresh_token": refresh_token,
                "access_token_expires_at": time.time(),
            })
            logger.info("Initialized tokens from .env")

    async def refresh_access_token(self) -> bool:
        """
        Refresh the access token using the refresh token.

        Returns:
            True if refresh successful, False otherwise
        """
        if not self.refresh_token:
            logger.error("No refresh token available for token refresh")
            return False

        try:
            logger.info("Attempting to refresh access token")

            path = "/api/v2/auth/access_token/get"
            timestamp = int(time.time())

            # Generate signature for refresh request (no access_token needed for refresh)
            base_string = f"{self.partner_id}{path}{timestamp}"
            signature = hmac.new(
                self.partner_key.encode("utf-8"),
                base_string.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            url = (
                f"{self.host_api}{path}?"
                f"partner_id={self.partner_id}&timestamp={timestamp}&sign={signature}"
            )

            payload = {
                "refresh_token": self.refresh_token,
                "partner_id": self.partner_id,
                "shop_id": self.shop_id,
            }

            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            # Handle response structure
            response_data = data.get("response") or data

            if "access_token" in response_data and "refresh_token" in response_data:
                self.access_token = response_data["access_token"]
                self.refresh_token = response_data["refresh_token"]

                # Save tokens to storage
                tokens = {
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "access_token_expires_at": time.time() + response_data.get("expire_in", TOKEN_EXPIRATION_DEFAULT),
                }
                save_tokens(tokens)
                logger.info("Access token refreshed successfully")
                return True
            else:
                logger.error(f"Token refresh failed, missing tokens in response: {data}")
                return False

        except Exception as e:
            logger.error(f"Error refreshing token: {e}", exc_info=True)
            return False

    async def ensure_valid_token(self) -> bool:
        """
        Ensure the access token is valid, refreshing if necessary.

        Returns:
            True if token is valid, False if refresh failed
        """
        stored_tokens = load_tokens()

        if stored_tokens:
            expires_at = stored_tokens.get("access_token_expires_at", 0)
            if is_token_expired(expires_at):
                logger.info("Token expired, refreshing...")
                return await self.refresh_access_token()

        return True

    def _generate_signature(
        self,
        path: str,
        timestamp: int,
    ) -> str:
        """
        Generate HMAC-SHA256 signature for API request.

        Base string format: {partner_id}{path}{timestamp}{access_token}{shop_id}
        """
        base_string = f"{self.partner_id}{path}{timestamp}{self.access_token}{self.shop_id}"

        signature = hmac.new(
            self.partner_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        logger.debug(f"Generated signature for {path}: {signature[:16]}...")
        return signature

    async def _make_request(
        self,
        path: str,
        params: Optional[dict] = None,
    ) -> dict:
        """
        Make authenticated GET request to Shopee API.

        Args:
            path: API endpoint path (e.g., "/api/v2/order/get_order_detail")
            params: Query parameters to include (order_sn_list, response_optional_fields, etc.)

        Returns:
            Parsed JSON response from API
        """
        # Ensure valid token before making request
        token_valid = await self.ensure_valid_token()
        if not token_valid:
            logger.error("Failed to ensure valid token")
            raise Exception("Token validation failed")

        # Generate timestamp and signature
        timestamp = int(time.time())
        signature = self._generate_signature(path, timestamp)

        # Build query parameters
        query_params = {
            "partner_id": self.partner_id,
            "timestamp": timestamp,
            "access_token": self.access_token,
            "shop_id": self.shop_id,
            "sign": signature,
        }

        # Add custom parameters
        if params:
            query_params.update(params)

        # Construct full URL
        url = f"{self.host_api}{path}"

        try:
            logger.info(f"Making API request to {path}")
            response = await self.client.get(url, params=query_params)
            response.raise_for_status()

            data = response.json()

            # Check for API-level errors using Shopee's error format
            if data.get("message") == "error" or data.get("error"):
                error_msg = data.get("message", "Unknown error")
                error_response = data.get("error_response", {})
                logger.error(f"API error calling {path}: {error_msg} - {error_response}")
                raise Exception(f"Shopee API error: {error_msg}")

            return data

        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling {path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error calling {path}: {e}")
            raise

    async def get_order_detail(self, order_sn_list: List[str]) -> dict:
        """
        Fetch order details from Shopee API.

        Args:
            order_sn_list: List of order SNs to fetch (max 50)

        Returns:
            API response with order_list containing all order details
        """
        # Shopee expects comma-separated order_sn_list with URL encoding
        order_sn_str = ",".join(order_sn_list)

        params = {
            "order_sn_list": order_sn_str,
            "response_optional_fields": (
                "buyer_username,item_list,total_amount,order_status,"
                "order_income,create_time"
            ),
        }

        return await self._make_request(GET_ORDER_DETAIL, params)

    async def get_escrow_detail(self, order_sn: str) -> dict:
        """
        Fetch escrow/settlement details for an order from Payment API.

        This provides the actual payout amount (escrow_amount) and per-item breakdown.

        Args:
            order_sn: Single order SN to fetch escrow details for

        Returns:
            API response with order_income containing escrow_amount and items
        """
        path = "/api/v2/payment/get_escrow_detail"

        params = {
            "order_sn": order_sn,
        }

        return await self._make_request(path, params)

    async def close(self) -> None:
        """Close HTTP client connection."""
        await self.client.aclose()
