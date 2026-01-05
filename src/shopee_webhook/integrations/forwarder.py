"""Forward webhooks to custom service."""

import httpx
from typing import Any, Dict, Optional

from shopee_webhook.core.logger import setup_logger

logger = setup_logger(__name__)


class WebhookForwarder:
    """Forwards webhook data to a custom service."""

    def __init__(self, forward_url: Optional[str] = None):
        """
        Initialize forwarder.

        Args:
            forward_url: URL to forward webhooks to (None = disabled)
        """
        self.forward_url = forward_url
        self.enabled = bool(forward_url)

        if self.enabled:
            logger.info(f"Webhook forwarding enabled to: {forward_url}")
        else:
            logger.info("Webhook forwarding disabled (no FORWARD_WEBHOOK_URL set)")

    async def forward_webhook(
        self,
        event_payload: Dict[str, Any],
        order_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Forward webhook event and order data to custom service.

        Args:
            event_payload: Raw webhook event from Shopee
            order_data: Formatted order data from API (if available)

        Returns:
            True if forwarding succeeded, False otherwise
        """
        if not self.enabled:
            logger.debug("Forwarding disabled, skipping")
            return False

        try:
            # Prepare payload
            payload = {
                "event": event_payload,
                "order_data": order_data,
            }

            # Forward to custom service
            logger.info(f"Forwarding webhook to {self.forward_url}")

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.forward_url,
                    json=payload,
                )

                response.raise_for_status()

                logger.info(
                    f"Successfully forwarded webhook (status={response.status_code})"
                )
                return True

        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error forwarding webhook: {e.response.status_code} - {e.response.text}"
            )
            return False

        except httpx.TimeoutException:
            logger.error(f"Timeout forwarding webhook to {self.forward_url}")
            return False

        except Exception as e:
            logger.error(f"Error forwarding webhook: {e}", exc_info=True)
            return False
