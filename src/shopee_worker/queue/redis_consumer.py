"""Redis consumer worker for processing webhooks from queue.

Consumer side of the message queue architecture.
Polls Redis queue with BRPOP, processes webhooks with retry logic, and handles DLQ.
"""

import json
import time
import asyncio
from typing import Dict, Any

import redis.asyncio as redis

from shopee_api.core.logger import setup_logger
from shopee_api.config.settings import settings
from shopee_worker.services.webhook_processor import WebhookProcessor

logger = setup_logger(__name__)

# Queue names (must match producer)
QUEUE_MAIN = "shopee:webhooks:main"
QUEUE_DLQ = "shopee:webhooks:dead_letter"
QUEUE_STATS = "shopee:webhooks:stats"


class RedisWebhookConsumer:
    """Consumes webhooks from Redis queue and processes them.

    Features:
    - BRPOP polling with timeout for graceful shutdown
    - Exponential backoff retry logic
    - Dead letter queue for failed messages
    - Statistics tracking
    """

    def __init__(
        self,
        redis_pool: redis.ConnectionPool,
        webhook_processor: WebhookProcessor,
        worker_id: int
    ):
        """Initialize Redis consumer worker.

        Args:
            redis_pool: Shared Redis connection pool
            webhook_processor: WebhookProcessor instance for business logic
            worker_id: Unique worker identifier (1-N)
        """
        self.redis = redis.Redis(connection_pool=redis_pool)
        self.processor = webhook_processor
        self.worker_id = worker_id
        self.is_running = False
        self.current_message = None
        self.redis_brpop_timeout = settings.redis_brpop_timeout
        self.stats = {
            "messages_processed": 0,
            "messages_failed": 0,
            "avg_processing_time": 0.0,
            "last_message_at": None
        }

        logger.info(f"Worker-{self.worker_id} initialized")

    async def start(self):
        """Start consuming messages (blocking loop).

        Continuously polls Redis queue with BRPOP and processes messages.
        Blocks until is_running is set to False (graceful shutdown).
        """
        self.is_running = True
        logger.info(f"Worker-{self.worker_id} started, polling queue...")

        while self.is_running:
            try:
                # BRPOP with configurable timeout (allows checking is_running flag)
                result = await self.redis.brpop(QUEUE_MAIN, timeout=self.redis_brpop_timeout)

                if result:
                    # result is tuple: (queue_name, message_json)
                    _, raw_message = result
                    message = json.loads(raw_message)
                    await self._process_message(message)

            except asyncio.CancelledError:
                logger.info(f"Worker-{self.worker_id} cancelled")
                break

            except json.JSONDecodeError as e:
                logger.error(f"Worker-{self.worker_id} invalid JSON: {e}")
                # Skip malformed message
                continue

            except Exception as e:
                logger.error(
                    f"Worker-{self.worker_id} error in main loop: {e}",
                    exc_info=True
                )
                # Brief pause before continuing to avoid tight error loop
                await asyncio.sleep(1)

        logger.info(f"Worker-{self.worker_id} stopped")

    async def _process_message(self, message: Dict[str, Any]):
        """Process single webhook message with retry logic.

        Args:
            message: Webhook message from queue with format:
                {
                    "id": "wh_timestamp_ordersn",
                    "payload": {...},
                    "metadata": {"enqueued_at": ..., "retry_count": ..., "max_retries": ...}
                }
        """
        queue_id = message.get("id", "unknown")
        payload = message.get("payload", {})
        metadata = message.get("metadata", {})

        order_sn = payload.get("data", {}).get("ordersn", "unknown")
        logger.info(f"Worker-{self.worker_id} processing: {queue_id} (order={order_sn})")

        self.current_message = queue_id
        start_time = time.time()

        # Try processing with retries
        success = await self._process_with_retry(payload, metadata)

        duration = time.time() - start_time
        self.stats["last_message_at"] = time.time()

        # Update statistics
        if success:
            self.stats["messages_processed"] += 1
            logger.info(
                f"Worker-{self.worker_id} completed: {queue_id} ({duration:.2f}s)"
            )

            # Update global stats
            await self._update_stats("total_processed", 1)

        else:
            self.stats["messages_failed"] += 1
            logger.error(
                f"Worker-{self.worker_id} failed: {queue_id} after retries"
            )

            # Update global stats
            await self._update_stats("total_failed", 1)

        # Update average processing time
        total_processed = self.stats["messages_processed"]
        if total_processed > 0:
            current_avg = self.stats["avg_processing_time"]
            self.stats["avg_processing_time"] = (
                (current_avg * (total_processed - 1) + duration) / total_processed
            )

        self.current_message = None

    async def _process_with_retry(
        self,
        payload: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> bool:
        """Process webhook with exponential backoff retry.

        Args:
            payload: Raw webhook event payload
            metadata: Message metadata with retry_count and max_retries

        Returns:
            True if processing succeeded, False if all retries exhausted
        """
        retry_count = metadata.get("retry_count", 0)
        max_retries = metadata.get("max_retries", 3)

        for attempt in range(retry_count, max_retries + 1):
            try:
                # Call existing webhook processor business logic
                success = await self.processor.process_webhook(payload)

                if success:
                    return True

                # Processing failed (but no exception), retry
                if attempt < max_retries:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(
                        f"Worker-{self.worker_id} retry {attempt+1}/{max_retries} "
                        f"in {wait_time}s (processing returned False)"
                    )
                    await asyncio.sleep(wait_time)

            except Exception as e:
                logger.error(
                    f"Worker-{self.worker_id} attempt {attempt+1} exception: {e}",
                    exc_info=True
                )

                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"Worker-{self.worker_id} retry {attempt+1}/{max_retries} "
                        f"in {wait_time}s"
                    )
                    await asyncio.sleep(wait_time)

        # Max retries exceeded, move to DLQ
        await self._move_to_dead_letter(payload, metadata)
        return False

    async def _move_to_dead_letter(
        self,
        payload: Dict[str, Any],
        metadata: Dict[str, Any]
    ):
        """Move failed message to dead letter queue.

        Args:
            payload: Original webhook payload
            metadata: Message metadata
        """
        try:
            dlq_message = {
                "payload": payload,
                "metadata": {
                    **metadata,
                    "moved_to_dlq_at": time.time(),
                    "worker_id": self.worker_id
                }
            }

            await self.redis.lpush(QUEUE_DLQ, json.dumps(dlq_message))

            order_sn = payload.get("data", {}).get("ordersn", "unknown")
            logger.error(
                f"Worker-{self.worker_id} moved to DLQ: order={order_sn}"
            )

        except Exception as e:
            logger.error(
                f"Worker-{self.worker_id} failed to move to DLQ: {e}",
                exc_info=True
            )

    async def _update_stats(self, field: str, increment: int = 1):
        """Update global statistics in Redis hash.

        Args:
            field: Field name in stats hash
            increment: Amount to increment
        """
        try:
            await self.redis.hincrby(QUEUE_STATS, field, increment)
        except Exception as e:
            logger.warning(
                f"Worker-{self.worker_id} failed to update stats {field}: {e}"
            )

    async def stop(self):
        """Graceful shutdown: finish current message, stop loop.

        Sets is_running to False, allowing the main loop to exit after
        completing the current message.
        """
        logger.info(f"Worker-{self.worker_id} stopping...")
        self.is_running = False

        if self.current_message:
            logger.info(
                f"Worker-{self.worker_id} waiting for current message: "
                f"{self.current_message}"
            )
            # The main loop will finish processing current message before exiting

    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics.

        Returns:
            Dict with worker metrics
        """
        return {
            "worker_id": self.worker_id,
            "is_running": self.is_running,
            "current_message": self.current_message,
            **self.stats
        }
