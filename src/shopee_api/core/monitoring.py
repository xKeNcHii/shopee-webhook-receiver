"""
GlitchTip Error Monitoring Utilities

Helper functions for error tracking and context management.
"""

from typing import Dict, Any, Optional
from shopee_api.core.logger import setup_logger

logger = setup_logger(__name__)


def set_webhook_context(
    event_code: int,
    shop_id: Optional[int] = None,
    order_sn: Optional[str] = None,
    **extra_tags
) -> None:
    """
    Set webhook-specific context for error tracking.

    Args:
        event_code: Shopee webhook event code
        shop_id: Shop ID
        order_sn: Order serial number
        **extra_tags: Additional tags to add
    """
    try:
        import sentry_sdk

        # Set tags
        sentry_sdk.set_tag("webhook.event_code", event_code)
        if shop_id:
            sentry_sdk.set_tag("webhook.shop_id", shop_id)
        if order_sn:
            sentry_sdk.set_tag("webhook.order_sn", order_sn)

        # Add extra tags
        for key, value in extra_tags.items():
            sentry_sdk.set_tag(key, value)

        # Set context
        context_data = {
            "event_code": event_code,
            "shop_id": shop_id,
            "order_sn": order_sn,
        }
        context_data.update(extra_tags)
        sentry_sdk.set_context("webhook", context_data)

    except ImportError:
        pass  # Sentry not installed or GlitchTip not configured
    except Exception as e:
        logger.warning(f"Failed to set webhook context: {e}")


def capture_exception(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    level: str = "error"
) -> None:
    """
    Capture an exception and send to GlitchTip.

    Args:
        error: The exception to capture
        context: Additional context data
        level: Error level (error, warning, info)
    """
    try:
        import sentry_sdk

        if context:
            with sentry_sdk.push_scope() as scope:
                scope.set_context("custom", context)
                scope.level = level
                sentry_sdk.capture_exception(error)
        else:
            sentry_sdk.capture_exception(error, level=level)

    except ImportError:
        pass  # Sentry not installed
    except Exception as e:
        logger.warning(f"Failed to capture exception in GlitchTip: {e}")


def capture_message(
    message: str,
    level: str = "info",
    context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Capture a message and send to GlitchTip.

    Args:
        message: Message to capture
        level: Message level (info, warning, error)
        context: Additional context data
    """
    try:
        import sentry_sdk

        if context:
            with sentry_sdk.push_scope() as scope:
                scope.set_context("custom", context)
                scope.level = level
                sentry_sdk.capture_message(message)
        else:
            sentry_sdk.capture_message(message, level=level)

    except ImportError:
        pass  # Sentry not installed
    except Exception as e:
        logger.warning(f"Failed to capture message in GlitchTip: {e}")
