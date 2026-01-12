"""
Rate-Limited Telegram Message Queue

Prevents "Too Many Requests" errors by queuing messages and sending at controlled rate.
Telegram limits: 20 messages per minute per chat for group chats.
We use 15 messages per minute (one every 4 seconds) for safety margin.
"""

import asyncio
import time
from typing import Any, Dict, Optional
from datetime import datetime

from shopee_api.core.logger import setup_logger

logger = setup_logger(__name__)

# Constants
DEFAULT_MESSAGES_PER_MINUTE = 15
MAX_RETRIES = 3
QUEUE_POLL_TIMEOUT = 1.0
LONG_WAIT_THRESHOLD = 5
STOP_TIMEOUT = 30.0


class TelegramMessageQueue:
    """
    Async queue with rate limiting for Telegram messages.

    Processes messages at a controlled rate to avoid hitting Telegram API limits.
    Messages are queued and sent sequentially with appropriate delays.
    """

    def __init__(self, messages_per_minute: int = DEFAULT_MESSAGES_PER_MINUTE):
        """
        Initialize the message queue.

        Args:
            messages_per_minute: Max messages to send per minute (default: 15)
        """
        self.queue = asyncio.Queue()
        self.messages_per_minute = messages_per_minute
        self.seconds_per_message = 60.0 / messages_per_minute
        self.last_send_time = 0
        self.is_running = False
        self.worker_task = None
        self.stats = {
            "total_queued": 0,
            "total_sent": 0,
            "total_failed": 0,
            "queue_size": 0,
        }

        logger.info(f"Telegram queue initialized: {messages_per_minute} msgs/min (1 every {self.seconds_per_message:.1f}s)")

    async def add_message(
        self,
        notifier,
        event_code: int,
        shop_id: int,
        event_data: Dict[str, Any],
        order_update_info: Optional[Dict[str, Any]] = None,
    ):
        """
        Add a message to the queue.

        Args:
            notifier: TelegramNotifier instance to use for sending
            event_code: Shopee event code
            shop_id: Shop ID
            event_data: Event payload data
            order_update_info: Optional order update info
        """
        message_item = {
            "notifier": notifier,
            "event_code": event_code,
            "shop_id": shop_id,
            "event_data": event_data,
            "order_update_info": order_update_info,
            "queued_at": time.time(),
        }

        await self.queue.put(message_item)
        self.stats["total_queued"] += 1
        self.stats["queue_size"] = self.queue.qsize()

        logger.debug(f"Message queued for event {event_code} (queue size: {self.queue.qsize()})")

    async def _send_with_retry(
        self,
        notifier,
        event_code: int,
        shop_id: int,
        event_data: Dict[str, Any],
        order_update_info: Optional[Dict[str, Any]] = None,
        max_retries: int = MAX_RETRIES,
    ) -> bool:
        """
        Send message with retry logic for rate limiting.

        Args:
            notifier: TelegramNotifier instance
            event_code: Shopee event code
            shop_id: Shop ID
            event_data: Event payload data
            order_update_info: Optional order update info
            max_retries: Maximum retry attempts

        Returns:
            True if sent successfully, False otherwise
        """
        for attempt in range(max_retries):
            try:
                # Use the direct send method (bypassing queue)
                success = notifier._send_direct(
                    event_code=event_code,
                    shop_id=shop_id,
                    event_data=event_data,
                    order_update_info=order_update_info,
                )

                if success:
                    self.stats["total_sent"] += 1
                    return True
                else:
                    # Send failed, check if we should retry
                    if attempt < max_retries - 1:
                        retry_delay = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                        logger.warning(f"Send failed for event {event_code}, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(f"Send failed for event {event_code} after {max_retries} attempts")
                        self.stats["total_failed"] += 1
                        return False

            except Exception as e:
                logger.error(f"Error sending message for event {event_code}: {e}")
                if attempt < max_retries - 1:
                    retry_delay = 2 ** attempt
                    logger.warning(f"Retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"Failed to send after {max_retries} attempts: {e}")
                    self.stats["total_failed"] += 1
                    return False

        return False

    async def _process_queue(self):
        """
        Background worker that processes the queue with rate limiting.

        Continuously processes messages from the queue, ensuring we don't exceed
        the configured messages per minute rate.
        """
        logger.info("Telegram queue worker started")

        while self.is_running:
            try:
                # Get next message (with timeout to allow checking is_running)
                try:
                    message_item = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=QUEUE_POLL_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    continue

                # Calculate how long to wait to respect rate limit
                current_time = time.time()
                time_since_last_send = current_time - self.last_send_time

                if time_since_last_send < self.seconds_per_message:
                    wait_time = self.seconds_per_message - time_since_last_send
                    logger.debug(f"Rate limiting: waiting {wait_time:.2f}s before next send")
                    await asyncio.sleep(wait_time)

                # Send the message
                notifier = message_item["notifier"]
                event_code = message_item["event_code"]
                shop_id = message_item["shop_id"]
                event_data = message_item["event_data"]
                order_update_info = message_item["order_update_info"]
                queued_at = message_item["queued_at"]

                wait_duration = time.time() - queued_at
                if wait_duration > LONG_WAIT_THRESHOLD:
                    logger.info(f"Processing message for event {event_code} (waited {wait_duration:.1f}s in queue)")

                success = await self._send_with_retry(
                    notifier=notifier,
                    event_code=event_code,
                    shop_id=shop_id,
                    event_data=event_data,
                    order_update_info=order_update_info,
                )

                self.last_send_time = time.time()
                self.stats["queue_size"] = self.queue.qsize()

                # Mark task as done
                self.queue.task_done()

            except asyncio.CancelledError:
                logger.info("Queue worker cancelled")
                break
            except Exception as e:
                logger.error(f"Error in queue worker: {e}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause before continuing

        logger.info("Telegram queue worker stopped")

    async def start(self):
        """Start the queue worker."""
        if self.is_running:
            logger.warning("Queue worker already running")
            return

        self.is_running = True
        self.worker_task = asyncio.create_task(self._process_queue())
        logger.info("Telegram queue worker task created")

    async def stop(self):
        """Stop the queue worker gracefully."""
        if not self.is_running:
            return

        logger.info("Stopping Telegram queue worker...")
        self.is_running = False

        if self.worker_task:
            # Wait for current message to complete
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

        # Process remaining messages in queue (with timeout)
        remaining = self.queue.qsize()
        if remaining > 0:
            logger.info(f"Processing {remaining} remaining messages in queue...")
            try:
                await asyncio.wait_for(self.queue.join(), timeout=STOP_TIMEOUT)
                logger.info("All queued messages processed")
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for queue to empty ({self.queue.qsize()} messages remain)")

        logger.info(f"Queue worker stopped. Stats: {self.stats}")

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            **self.stats,
            "queue_size": self.queue.qsize(),
            "is_running": self.is_running,
            "messages_per_minute": self.messages_per_minute,
        }


# Global queue instance
_message_queue = None


def get_message_queue() -> TelegramMessageQueue:
    """Get or create the global message queue instance."""
    global _message_queue
    if _message_queue is None:
        _message_queue = TelegramMessageQueue(messages_per_minute=DEFAULT_MESSAGES_PER_MINUTE)
    return _message_queue


async def start_queue_worker():
    """Start the global queue worker."""
    queue = get_message_queue()
    await queue.start()


async def stop_queue_worker():
    """Stop the global queue worker."""
    queue = get_message_queue()
    await queue.stop()
