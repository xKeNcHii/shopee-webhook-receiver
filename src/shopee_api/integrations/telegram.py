#!/usr/bin/env python3
"""
Telegram Notifications for Shopee Webhooks

Sends real-time alerts to Telegram channel when webhooks arrive.
Runs asynchronously to avoid blocking webhook responses.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from shopee_api.core.logger import setup_logger

logger = setup_logger(__name__)

# Constants
MAX_MESSAGE_LENGTH = 4000
REQUEST_TIMEOUT = 5


class TelegramNotifier:
    """Send webhook events to Telegram channel."""

    # Map of event code to topic ID (dynamically populated)
    TOPIC_IDS = {}

    # Config file path
    CONFIG_FILE = Path("/app/config/telegram_topics.json")

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None
    ):
        """
        Initialize Telegram notifier.

        Args:
            bot_token: Telegram bot token (e.g., 123456:ABC-DEF...)
            chat_id: Telegram channel or chat ID (e.g., -1001234567890 or 123456789)
        """
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.info("Telegram notifications disabled (no credentials)")
            return

        self.api_url_send = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        self.api_url_topic = f"https://api.telegram.org/bot{self.bot_token}/createForumTopic"

        # Load topic IDs from config file
        self._load_topic_ids()

        logger.info(f"Telegram notifier initialized for chat: {self.chat_id}")

    def _load_topic_ids(self):
        """Load topic IDs from telegram_topics.json config file."""
        try:
            if self.CONFIG_FILE.exists():
                with open(self.CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    topics = config.get("topics", {})

                    for code_str, topic_info in topics.items():
                        code = int(code_str)
                        topic_id = topic_info.get("topic_id")
                        self.TOPIC_IDS[code] = topic_id
                        logger.info(f"Loaded topic ID {topic_id} for event code {code}")
            else:
                logger.info(f"Topic config file not found, will create on first use: {self.CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Error loading topic IDs: {e}")

    def _save_topic_id(self, event_code: int, topic_id: int):
        """Save topic ID to config file."""
        try:
            # Load existing config
            if self.CONFIG_FILE.exists():
                with open(self.CONFIG_FILE, 'r') as f:
                    config = json.load(f)
            else:
                config = {"topics": {}}

            # Add/update topic
            if "topics" not in config:
                config["topics"] = {}

            config["topics"][str(event_code)] = {
                "event_code": event_code,
                "topic_id": topic_id,
                "created_at": datetime.now().isoformat()
            }

            # Ensure config directory exists
            self.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Write config
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)

            logger.info(f"Saved topic ID {topic_id} for event code {event_code}")
        except Exception as e:
            logger.error(f"Error saving topic ID: {e}")

    def _create_topic(self, event_code: int) -> Optional[int]:
        """Create a new Telegram forum topic for the event code."""
        try:
            payload = {
                "chat_id": self.chat_id,
                "name": str(event_code)  # Topic name is just the event code
            }

            response = requests.post(self.api_url_topic, json=payload, timeout=REQUEST_TIMEOUT)

            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    topic_id = data["result"]["message_thread_id"]
                    logger.info(f"Created Telegram topic for event code {event_code}: topic_id={topic_id}")
                    # Save to config
                    self._save_topic_id(event_code, topic_id)
                    self.TOPIC_IDS[event_code] = topic_id
                    return topic_id
            else:
                logger.error(f"Failed to create topic: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error creating Telegram topic: {e}")
            return None

    def _ensure_topic_exists(self, event_code: int) -> Optional[int]:
        """Ensure topic exists for event code, create if needed."""
        # Check if topic already exists
        if event_code in self.TOPIC_IDS and self.TOPIC_IDS[event_code]:
            return self.TOPIC_IDS[event_code]

        # Topic doesn't exist, create it
        logger.info(f"Creating new topic for event code {event_code}")
        return self._create_topic(event_code)

    def format_webhook_message(
        self,
        event_code: int,
        shop_id: int,
        event_data: Dict[str, Any],
        order_update_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Format webhook event with two distinct sections:
        1) Shopee Webhook Event - What Shopee called back
        2) Order Details - Full order details fetched from API

        Args:
            event_code: Shopee event code
            shop_id: Shop ID
            event_data: Event payload data from webhook
            order_update_info: Optional order update info with order_data from API

        Returns:
            Formatted message string with two sections
        """
        # Map event codes to names
        event_names = {
            3: "Order Status Update",
            4: "Order Tracking Number",
            8: "Reserved Stock Change",
        }

        event_name = event_names.get(event_code, f"Event {event_code}")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        message = ""

        # ========== SECTION 1: SHOPEE WEBHOOK EVENT ==========
        message += f"📩 <b>SHOPEE WEBHOOK EVENT</b>\n"
        message += f"<b>Code:</b> {event_code} ({event_name})\n"
        message += f"<b>Shop ID:</b> <code>{shop_id}</code>\n"
        message += f"<b>Time:</b> {timestamp}\n"

        # Add webhook event data
        if event_data and isinstance(event_data, dict):
            message += f"\n<b>Event Data:</b>\n"
            for key, value in event_data.items():
                if len(str(value)) < 50:
                    message += f"  • {key}: <code>{value}</code>\n"

        # ========== SECTION 2: ORDER DETAILS ==========
        if order_update_info and event_code in [3, 4]:
            logger.debug(f"Order update info received: {order_update_info}")
            order_data = order_update_info.get("order_data", {})
            logger.debug(f"Order data extracted: {order_data}")

            if order_data:
                message += f"\n{'─' * 15}\n\n"
                message += f"📦 <b>ORDER DETAILS</b>\n\n"

                # Basic Order Information
                message += f"<b>🆔 Order Information</b>\n"
                message += f"  Order ID: <code>{order_data.get('order_id', 'N/A')}</code>\n"
                message += f"  Shop ID: {order_data.get('shop_id', 'N/A')}\n"
                message += f"  Status: <code>{order_data.get('status', 'N/A')}</code>\n"

                # Timestamps
                if order_data.get("create_time"):
                    message += f"  Created: {order_data.get('create_time')}\n"
                if order_data.get("update_time"):
                    message += f"  Updated: {order_data.get('update_time')}\n"

                # Buyer Information
                message += f"\n<b>👤 Buyer Information</b>\n"
                message += f"  Buyer: {order_data.get('buyer', 'N/A')}\n"

                # Recipient Address
                if order_data.get("recipient_address"):
                    addr = order_data.get("recipient_address", {})
                    message += f"\n<b>📍 Shipping Address</b>\n"
                    if addr.get("name"):
                        message += f"  Name: {addr.get('name')}\n"
                    if addr.get("phone"):
                        message += f"  Phone: {addr.get('phone')}\n"
                    if addr.get("full_address"):
                        message += f"  Address: {addr.get('full_address')}\n"
                    if addr.get("city"):
                        message += f"  City: {addr.get('city')}\n"
                    if addr.get("district"):
                        message += f"  District: {addr.get('district')}\n"
                    if addr.get("state"):
                        message += f"  State: {addr.get('state')}\n"

                # Financial Information
                message += f"\n<b>💰 Financial Information</b>\n"
                if order_data.get("total_amount"):
                    amount = order_data.get('total_amount')
                    currency = order_data.get('currency', 'SGD')
                    message += f"  Total Amount: <code>{amount} {currency}</code>\n"
                if order_data.get("payment_method"):
                    message += f"  Payment Method: {order_data.get('payment_method')}\n"

                # Shipping Information
                if order_data.get("shipping_carrier"):
                    message += f"\n<b>🚚 Shipping Information</b>\n"
                    message += f"  Carrier: {order_data.get('shipping_carrier')}\n"

                # Order Income (Escrow) Details
                if order_data.get("order_income") and order_data.get("order_income").get("escrow_amount_after_adjustment"):
                    income = order_data.get("order_income", {})
                    message += f"\n<b>💳 Escrow Information</b>\n"
                    message += f"  Amount: <code>{income.get('escrow_amount_after_adjustment')}</code>\n"
                    if income.get("escrow_items"):
                        message += f"  Escrow Items: {len(income.get('escrow_items', []))}\n"

                # Items Detail
                if order_data.get("items"):
                    message += f"\n<b>📋 Items ({order_data.get('item_count', 0)})</b>\n"
                    for idx, item in enumerate(order_data.get("items", []), 1):
                        message += f"\n  <b>{idx}. {item.get('product_name', 'N/A')}</b>\n"

                        # Item identifiers
                        if item.get('parent_sku'):
                            message += f"     Item SKU: <code>{item.get('parent_sku')}</code>\n"
                        if item.get('sku'):
                            message += f"     Model SKU: <code>{item.get('sku')}</code>\n"

                        # Item variation
                        if item.get('item_type'):
                            message += f"     Variation: {item.get('item_type')}\n"

                        # Quantity
                        message += f"     Qty: {item.get('quantity', 'N/A')}\n"

        return message

    def _split_long_message(self, message: str, max_length: int = MAX_MESSAGE_LENGTH) -> List[str]:
        """
        Split a long message into chunks.

        Telegram limit is 4096 chars. We use 4000 as safety margin.

        Args:
            message: Message to split
            max_length: Maximum length per chunk

        Returns:
            List of message chunks
        """
        if len(message) <= max_length:
            return [message]

        chunks = []
        lines = message.split("\n")
        current_chunk = ""

        for line in lines:
            if len(current_chunk) + len(line) + 1 <= max_length:
                current_chunk += line + "\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = line + "\n"

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks if chunks else [message[:max_length]]

    def _send_direct(
        self,
        event_code: int,
        shop_id: int,
        event_data: Dict[str, Any],
        order_update_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send webhook event to Telegram directly (used by queue worker).

        Automatically creates a new topic if one doesn't exist for this event code.
        Splits long messages into multiple parts if exceeding Telegram's 4096 char limit.

        Args:
            event_code: Shopee event code
            shop_id: Shop ID
            event_data: Event payload data
            order_update_info: Optional order update info for enhanced formatting

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            return False

        try:
            # Ensure topic exists (create if needed)
            topic_id = self._ensure_topic_exists(event_code)

            message = self.format_webhook_message(
                event_code, shop_id, event_data, order_update_info
            )

            # Split message if too long
            message_chunks = self._split_long_message(message)

            all_sent = True
            for idx, chunk in enumerate(message_chunks, 1):
                payload = {
                    "chat_id": self.chat_id,
                    "text": chunk,
                    "parse_mode": "HTML"
                }

                # Send to topic if we have one
                if topic_id:
                    payload["message_thread_id"] = topic_id

                response = requests.post(self.api_url_send, json=payload, timeout=REQUEST_TIMEOUT)

                if response.status_code == 200:
                    if len(message_chunks) > 1:
                        part_info = f" (Part {idx}/{len(message_chunks)})"
                    else:
                        part_info = ""
                    topic_info = f" (Topic {topic_id})" if topic_id else ""
                    logger.info(f"Telegram notification sent for event {event_code}{part_info}{topic_info}")
                else:
                    logger.error(
                        f"Telegram API error: {response.status_code} - {response.text}"
                    )
                    all_sent = False

            return all_sent

        except requests.exceptions.Timeout:
            logger.error("Telegram notification timeout")
            return False
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")
            return False

    def send_event(
        self,
        event_code: int,
        shop_id: int,
        event_data: Dict[str, Any],
        order_update_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Queue webhook event for Telegram sending with rate limiting.

        Messages are added to a queue and sent at a controlled rate to avoid
        hitting Telegram's "Too Many Requests" (429) errors.

        Args:
            event_code: Shopee event code
            shop_id: Shop ID
            event_data: Event payload data
            order_update_info: Optional order update info for enhanced formatting

        Returns:
            True (message queued successfully)
        """
        if not self.enabled:
            return False

        try:
            # Import here to avoid circular dependency
            from shopee_api.integrations.telegram_queue import get_message_queue
            import asyncio

            queue = get_message_queue()

            # Add to queue (create task in event loop)
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # No event loop in current thread, create one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Queue the message
            asyncio.create_task(
                queue.add_message(
                    notifier=self,
                    event_code=event_code,
                    shop_id=shop_id,
                    event_data=event_data,
                    order_update_info=order_update_info,
                )
            )

            return True

        except Exception as e:
            logger.error(f"Error queuing Telegram notification: {e}")
            return False


# Global notifier instance
_notifier = None


def get_notifier() -> TelegramNotifier:
    """
    Get or create global Telegram notifier instance.

    Checks runtime config first, then falls back to environment variables.
    """
    global _notifier
    if _notifier is None:
        # Check runtime config first (allows dashboard updates)
        try:
            from shopee_api.core.runtime_config import runtime_config
            telegram_cfg = runtime_config.get_telegram_config()

            # If runtime config has settings, use them
            if telegram_cfg and telegram_cfg.get("bot_token"):
                _notifier = TelegramNotifier(
                    bot_token=telegram_cfg.get("bot_token"),
                    chat_id=telegram_cfg.get("chat_id")
                )
                logger.info("Using Telegram config from runtime_config.json")
            else:
                # Fall back to environment variables
                _notifier = TelegramNotifier()
                logger.info("Using Telegram config from environment variables")
        except Exception as e:
            # If runtime config fails, fall back to env vars
            logger.warning(f"Could not load runtime config, using env vars: {e}")
            _notifier = TelegramNotifier()

    return _notifier


def send_webhook_to_telegram(
    event_code: int,
    shop_id: int,
    event_data: Dict[str, Any],
    order_update_info: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send webhook event to Telegram (convenience function).

    Args:
        event_code: Shopee event code
        shop_id: Shop ID
        event_data: Event payload data
        order_update_info: Optional order update info for enhanced formatting

    Returns:
        True if notification sent successfully, False otherwise
    """
    notifier = get_notifier()
    if notifier.enabled:
        # Send asynchronously in background (non-blocking)
        try:
            return notifier.send_event(event_code, shop_id, event_data, order_update_info)
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False
    return False
