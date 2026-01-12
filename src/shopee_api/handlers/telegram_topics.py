"""Telegram Topics Handler

Create and manage Telegram supergroup topics for organizing webhook events.
"""

import json
from pathlib import Path
from typing import Optional

import requests

from shopee_api.core.logger import setup_logger
from shopee_api.config.settings import settings

logger = setup_logger(__name__)

# Event code to topic name mapping
EVENT_TOPIC_NAMES = {
    3: "Order Status Updates",
    4: "Tracking Number Updates",
    8: "Stock Changes",
}


async def create_telegram_topics(chat_id: int) -> bool:
    """
    Create Telegram topics for organizing webhook events.

    Args:
        chat_id: Telegram chat ID

    Returns:
        True if successful
    """
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not configured")
        return False

    config_file = Path(__file__).parent.parent.parent.parent / "config" / "telegram_topics.json"
    topics_config = {
        "topics": {}
    }

    for event_code, topic_name in EVENT_TOPIC_NAMES.items():
        try:
            # Create topic in Telegram
            api_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/createForumTopic"
            payload = {
                "chat_id": chat_id,
                "name": topic_name,
                "icon_color": 16711680,  # Red
                "icon_emoji_id": None
            }

            response = requests.post(api_url, json=payload, timeout=10)
            data = response.json()

            if data.get("ok"):
                topic_id = data["result"]["message_thread_id"]
                topics_config["topics"][str(event_code)] = {
                    "event_type": event_code,
                    "event_name": topic_name,
                    "topic_id": topic_id
                }
                logger.info(f"Created topic '{topic_name}' (code {event_code}, topic_id {topic_id})")
            else:
                logger.warning(f"Failed to create topic for code {event_code}: {data.get('description')}")

        except Exception as e:
            logger.error(f"Error creating topic for code {event_code}: {e}")

    # Save topics config
    try:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, 'w') as f:
            json.dump(topics_config, f, indent=2)
        logger.info(f"Saved topic configuration to {config_file}")
    except Exception as e:
        logger.error(f"Error saving topic configuration: {e}")

    return True


def load_topic_ids() -> dict:
    """
    Load topic IDs from configuration file.

    Returns:
        Dictionary mapping event codes to topic IDs
    """
    config_file = Path(__file__).parent.parent.parent.parent / "config" / "telegram_topics.json"

    if not config_file.exists():
        return {}

    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
            topics = {}
            for code_str, topic_info in config.get("topics", {}).items():
                topics[int(code_str)] = topic_info.get("topic_id")
            return topics
    except Exception as e:
        logger.error(f"Error loading topic configuration: {e}")
        return {}
