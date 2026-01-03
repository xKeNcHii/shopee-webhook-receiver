#!/usr/bin/env python3
"""
Shipping Document Handler

Handles shipping_document_status_push (Code 15) webhooks.
Fetches and sends waybills to Telegram when ready.
"""

import time
from typing import Any, Dict, Optional

import requests

from shopee_webhook.config.settings import settings
from shopee_webhook.core.logger import setup_logger
from shopee_webhook.utils.shopee_api import get_signed_url

logger = setup_logger(__name__)


def fetch_shipping_document(order_sn: str, package_number: str) -> Optional[bytes]:
    """
    Fetch shipping document (waybill) from Shopee API.

    Args:
        order_sn: Order serial number
        package_number: Package number

    Returns:
        Document bytes if successful, None otherwise
    """
    try:
        timestamp = int(time.time())
        path = "/api/v2/logistics/get_shipping_document_info"
        signature = get_signed_url(path, timestamp, settings.access_token, settings.shop_id)

        url = (
            f"{settings.host_api}{path}?partner_id={settings.partner_id}&timestamp={timestamp}"
            f"&sign={signature}&access_token={settings.access_token}&shop_id={settings.shop_id}"
            f"&order_sn={order_sn}&package_number={package_number}"
        )

        logger.info(f"Fetching shipping document for order {order_sn}, package {package_number}")

        response = requests.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()

        if data.get("error"):
            logger.error(f"API Error: {data.get('message')}")
            return None

        response_data = data.get("response", {})

        # The API returns document info
        # You may need to fetch the actual PDF/image from a URL
        if response_data.get("shipping_document_url"):
            doc_url = response_data["shipping_document_url"]
            logger.info(f"Got document URL: {doc_url}")

            # Fetch the actual document
            doc_response = requests.get(doc_url, timeout=10)
            if doc_response.status_code == 200:
                return doc_response.content

        logger.warning(f"No shipping document URL in response: {response_data}")
        return None

    except Exception as e:
        logger.error(f"Error fetching shipping document: {e}")
        return None


def handle_shipping_document_ready(
    order_sn: str,
    package_number: str,
    event_data: Dict[str, Any],
    telegram_notifier = None
) -> bool:
    """
    Handle shipping document ready event.

    Args:
        order_sn: Order serial number
        package_number: Package number
        event_data: Webhook event data
        telegram_notifier: TelegramNotifier instance

    Returns:
        True if handled successfully
    """
    status = event_data.get("status", "").upper()

    if status != "READY":
        logger.info(f"Shipping document status is {status}, not READY. Skipping.")
        return False

    logger.info(f"Shipping document READY for order {order_sn}")

    # Fetch the document
    doc_bytes = fetch_shipping_document(order_sn, package_number)

    if not doc_bytes:
        logger.warning(f"Failed to fetch shipping document for {order_sn}")
        return False

    # Send to Telegram if notifier available
    if telegram_notifier and telegram_notifier.enabled:
        try:
            send_waybill_to_telegram(
                telegram_notifier,
                order_sn,
                package_number,
                doc_bytes
            )
        except Exception as e:
            logger.error(f"Error sending waybill to Telegram: {e}")

    return True


def send_waybill_to_telegram(
    telegram_notifier,
    order_sn: str,
    package_number: str,
    doc_bytes: bytes
) -> bool:
    """
    Send waybill document to Telegram.

    Args:
        telegram_notifier: TelegramNotifier instance
        order_sn: Order serial number
        package_number: Package number
        doc_bytes: Document file bytes

    Returns:
        True if sent successfully
    """
    if not telegram_notifier.enabled:
        return False

    try:
        from io import BytesIO
        import requests as http_requests

        # Prepare file
        file_obj = BytesIO(doc_bytes)
        filename = f"waybill_{order_sn}_{package_number}.pdf"

        # Prepare message
        caption = (
            f"📄 <b>Shipping Waybill Ready</b>\n\n"
            f"<b>Order SN:</b> <code>{order_sn}</code>\n"
            f"<b>Package:</b> <code>{package_number}</code>\n"
            f"<b>Status:</b> READY"
        )

        # Send to Telegram
        api_url = f"https://api.telegram.org/bot{telegram_notifier.bot_token}/sendDocument"

        files = {
            'document': (filename, file_obj, 'application/pdf')
        }

        data = {
            'chat_id': telegram_notifier.chat_id,
            'caption': caption,
            'parse_mode': 'HTML',
            'message_thread_id': telegram_notifier.TOPIC_IDS.get(15)  # Code 15 topic
        }

        response = http_requests.post(api_url, files=files, data=data, timeout=10)

        if response.status_code == 200:
            logger.info(f"Sent waybill to Telegram for order {order_sn}")
            return True
        else:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"Error sending waybill to Telegram: {e}")
        return False
