"""API routes for webhook receiver."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Header, Request, Response

from shopee_webhook.core.logger import setup_logger
from shopee_webhook.core.signature import validate_webhook_request
from shopee_webhook.handlers.webhook import handle_webhook_event
from shopee_webhook.integrations.telegram import get_notifier
from shopee_webhook.integrations.forwarder import WebhookForwarder
from shopee_webhook.api.client import ShopeeAPIClient
from shopee_webhook.config.settings import settings
from shopee_webhook.services.order_service import OrderService

logger = setup_logger(__name__)
router = APIRouter()


@router.get("/")
async def root() -> dict:
    """Root endpoint with basic service info."""
    return {
        "service": "Shopee Webhook Receiver",
        "version": "1.0.0",
        "endpoints": {
            "webhook": "POST /webhook/shopee",
            "health": "GET /health",
            "docs": "GET /docs",
            "telegram_info": "GET /telegram/info",
        },
    }


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint for monitoring."""
    from pathlib import Path

    health_status = {
        "status": "healthy",
        "service": "shopee-webhook-forwarder",
        "checks": {},
    }

    # Check configuration files
    config_checks = {}
    if Path("config/shopee_tokens.json").exists():
        config_checks["tokens_file"] = "ok"
    else:
        config_checks["tokens_file"] = "missing"
        health_status["status"] = "degraded"

    if Path("config/telegram_topics.json").exists():
        config_checks["topics_file"] = "ok"
    else:
        config_checks["topics_file"] = "not_created_yet"

    health_status["checks"]["config"] = config_checks

    # Check required environment variables
    env_checks = {
        "partner_id": "ok" if settings.partner_id else "missing",
        "shop_id": "ok" if settings.shop_id else "missing",
        "telegram_bot_token": "ok" if settings.telegram_bot_token else "missing",
        "telegram_chat_id": "ok" if settings.telegram_chat_id else "missing",
    }

    missing_env = [k for k, v in env_checks.items() if v == "missing"]
    if missing_env:
        health_status["status"] = "degraded"

    health_status["checks"]["environment"] = env_checks

    # Check forwarding configuration
    if hasattr(settings, 'forward_webhook_url') and settings.forward_webhook_url:
        health_status["checks"]["forwarding"] = "enabled"
    else:
        health_status["checks"]["forwarding"] = "disabled"

    return health_status


@router.get("/telegram/info")
async def telegram_info() -> dict:
    """Get Telegram configuration info for debugging."""
    from shopee_webhook.config.settings import settings

    return {
        "bot_token": (
            settings.telegram_bot_token[:10] + "..."
            if settings.telegram_bot_token
            else "NOT SET"
        ),
        "chat_id": settings.telegram_chat_id,
        "configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "bot_name": "@exzennwebhooktest_bot",
        "instructions": "Send /info in Telegram chat to get your chat ID",
    }


@router.post("/telegram/update")
async def telegram_update(request: Request) -> dict:
    """Handle Telegram bot updates and commands."""
    try:
        import requests as req

        update = await request.json()
        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")

        if text == "/info":
            # Send chat ID info to user
            bot_token = settings.telegram_bot_token
            info_message = f"Chat ID: <code>{chat_id}</code>\n\nUse this Chat ID in your .env file as TELEGRAM_CHAT_ID"

            req.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": info_message,
                    "parse_mode": "HTML"
                },
                timeout=5
            )
            logger.info(f"Sent info to chat {chat_id}")

        elif text == "/setup_topics":
            # Create topics for each Push Code
            from shopee_webhook.handlers.telegram_topics import create_telegram_topics

            await create_telegram_topics(chat_id)

    except Exception as e:
        logger.error(f"Error processing Telegram update: {e}")

    return {"ok": True}


@router.post("/webhook/shopee")
async def shopee_webhook(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_shopee_signature: Optional[str] = Header(None),
) -> Response:
    """
    Main Shopee webhook endpoint - receives, validates, and forwards webhooks.

    Shopee sends HTTP POST requests to this URL with webhook events.
    All events are logged for analysis.

    **CRITICAL**: Response must be 2xx status with EMPTY body.
    This is required by Shopee to avoid repeated notifications.

    Args:
        request: The HTTP request from Shopee
        authorization: Authorization header with webhook signature
        x_shopee_signature: Signature from x-shopee-signature header

    Returns:
        Empty 200 response (as required by Shopee)
    """
    # Get raw body for signature verification
    raw_body = await request.body()

    # Quick validation and response
    try:
        body_str = raw_body.decode("utf-8")
        is_valid, error_msg = validate_webhook_request(raw_body, authorization)

        if not is_valid:
            logger.warning(f"Invalid webhook request: {error_msg}")
            # Still return 200 to prevent infinite Shopee retries
            return Response(content="", status_code=200)

        # Process webhook event
        try:
            event_payload = json.loads(body_str)

            # Create OrderService for fetching order details
            order_service = None
            try:
                api_client = ShopeeAPIClient(
                    partner_id=settings.partner_id,
                    partner_key=settings.partner_key,
                    shop_id=settings.shop_id,
                    access_token=settings.access_token,
                    refresh_token=settings.refresh_token,
                    host_api=settings.host_api,
                )
                order_service = OrderService(api_client)
            except Exception as e:
                logger.error(f"Failed to create OrderService: {e}")

            # Create forwarder if URL is configured
            forwarder = None
            if hasattr(settings, 'forward_webhook_url') and settings.forward_webhook_url:
                forwarder = WebhookForwarder(settings.forward_webhook_url)

            await handle_webhook_event(
                event_payload,
                authorization,
                order_service=order_service,
                forwarder=forwarder,
            )

            logger.info(
                f"Webhook received: code={event_payload.get('code')}, "
                f"shop_id={event_payload.get('shop_id')}"
            )
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")

    except Exception as e:
        logger.error(f"Webhook error: {e}")

    # **CRITICAL**: Return 2xx status with EMPTY body immediately
    # Do NOT return JSON or any body content
    return Response(content="", status_code=200)
