"""Forward webhooks to custom service."""

import httpx
import asyncio
from typing import Any, Dict, Optional

from shopee_api.core.logger import setup_logger

logger = setup_logger(__name__)

FORWARDER_TIMEOUT = 90.0
MAX_RETRIES = 3


class WebhookForwarder:
    """Forwards webhook data to a custom service.

    Supports two modes:
    1. Redis queue (preferred): Fast publish to Redis, workers process async
    2. HTTP forwarding (fallback): Direct HTTP POST to processor

    Circuit breaker automatically switches from Redis to HTTP on failures.
    """

    def __init__(
        self,
        forward_url: Optional[str] = None,
        redis_queue: Optional[Any] = None
    ):
        """
        Initialize forwarder.

        Args:
            forward_url: URL to forward webhooks to (None = disabled)
            redis_queue: Optional RedisWebhookQueue instance for async processing
        """
        self.forward_url = forward_url
        self.redis_queue = redis_queue
        self.enabled = bool(forward_url) or bool(redis_queue)

        if redis_queue:
            logger.info("Webhook forwarding enabled via Redis queue (preferred)")
        if forward_url:
            logger.info(f"Webhook forwarding via HTTP available: {forward_url}")
        if not self.enabled:
            logger.info("Webhook forwarding disabled (no queue or URL configured)")

    async def forward_webhook(
        self,
        event_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Forward raw webhook event to custom service.

        Strategy:
        1. Try Redis queue first (fast, async processing)
        2. Fall back to HTTP if Redis fails or circuit breaker opens

        Only the minimal webhook event from Shopee is forwarded.
        The processor can fetch full order details from Shopee API if needed.

        Args:
            event_payload: Raw webhook event from Shopee

        Returns:
            Dict with keys: success (bool), method (str), attempts (int), last_error (str|None)
        """
        if not self.enabled:
            logger.debug("Forwarding disabled, skipping")
            return {"success": False, "method": "none", "attempts": 0, "last_error": "Disabled"}

        # Try Redis first (preferred method)
        if self.redis_queue:
            redis_result = await self.redis_queue.publish(event_payload)

            if redis_result["success"]:
                logger.info(
                    f"Published to Redis: {redis_result['queue_id']} "
                    f"({redis_result.get('latency_ms', 0):.1f}ms)"
                )
                return {
                    "success": True,
                    "method": "redis",
                    "attempts": 1,
                    "last_error": None,
                    **redis_result
                }

            # Redis failed or circuit breaker opened
            if redis_result.get("fallback_used"):
                logger.warning(
                    f"Redis unavailable ({redis_result.get('error', 'unknown')}), "
                    "falling back to HTTP"
                )

        # Fallback to HTTP forwarding
        if self.forward_url:
            logger.info("Using HTTP fallback for webhook forwarding")
            http_result = await self._forward_via_http(event_payload)
            return {
                **http_result,
                "method": "http_fallback"
            }

        # Neither Redis nor HTTP available
        logger.error("No forwarding method available (Redis failed, no HTTP URL)")
        return {
            "success": False,
            "method": "none",
            "attempts": 0,
            "last_error": "No forwarding method available"
        }

    async def _forward_via_http(
        self,
        event_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Forward webhook via HTTP POST with retries.

        Args:
            event_payload: Raw webhook event from Shopee

        Returns:
            Dict with keys: success (bool), attempts (int), last_error (str|None)
        """

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Forward only the raw webhook event
                # Processor can fetch order details from Shopee API if needed
                if attempt == 1:
                    logger.info(f"HTTP forwarding webhook to {self.forward_url}")
                else:
                    logger.info(f"HTTP retry {attempt}/{MAX_RETRIES} to {self.forward_url}")

                # OPTIMIZATION: Increased timeout to 90s to handle slow worker processing
                async with httpx.AsyncClient(timeout=FORWARDER_TIMEOUT) as client:
                    response = await client.post(
                        self.forward_url,
                        json=event_payload,
                    )

                    response.raise_for_status()

                    logger.info(
                        f"Successfully forwarded via HTTP (status={response.status_code})"
                    )
                    return {
                        "success": True,
                        "attempts": attempt,
                        "last_error": None
                    }

            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text}"
                logger.error(f"HTTP error forwarding webhook: {last_error}")

                # Don't retry on 4xx errors (client error), retry on 5xx
                if 500 <= e.response.status_code < 600:
                    pass  # Retry server errors
                else:
                    return {
                        "success": False,
                        "attempts": attempt,
                        "last_error": last_error
                    }

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    f"HTTP attempt {attempt} failed: {last_error}"
                )
                # Continue to retry logic

            except Exception as e:
                last_error = str(e)
                logger.error(f"Unexpected HTTP error forwarding webhook: {e}", exc_info=True)
                return {
                    "success": False,
                    "attempts": attempt,
                    "last_error": last_error
                }

            # Calculate backoff and wait if not last attempt
            if attempt < MAX_RETRIES:
                retry_delay = 2 ** (attempt - 1)  # 1s, 2s
                logger.info(f"HTTP waiting {retry_delay}s before next retry...")
                await asyncio.sleep(retry_delay)

        logger.error(f"Failed HTTP forwarding after {MAX_RETRIES} attempts")
        return {
            "success": False,
            "attempts": MAX_RETRIES,
            "last_error": last_error
        }
