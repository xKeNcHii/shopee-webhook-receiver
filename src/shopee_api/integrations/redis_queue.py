"""Redis queue client for publishing webhooks.

Producer client for the forwarder to publish webhooks to Redis queue.
Includes circuit breaker integration for automatic HTTP fallback.
"""

import json
import time
from typing import Any, Dict, Optional

import redis.asyncio as redis

from shopee_api.core.logger import setup_logger
from shopee_api.integrations.circuit_breaker import RedisCircuitBreaker
from shopee_api.config.settings import settings

logger = setup_logger(__name__)

# Queue names
QUEUE_MAIN = "shopee:webhooks:main"
QUEUE_DLQ = "shopee:webhooks:dead_letter"
QUEUE_STATS = "shopee:webhooks:stats"


class RedisWebhookQueue:
    """Redis queue client for publishing webhooks.

    Features:
    - Async Redis connection pool
    - Circuit breaker for automatic fallback
    - Message format with metadata
    - Statistics tracking
    """

    def __init__(
        self,
        host: str = None,
        port: int = None,
        db: int = None,
        circuit_breaker: Optional[RedisCircuitBreaker] = None
    ):
        """Initialize Redis queue client.

        Args:
            host: Redis host (default from settings)
            port: Redis port (default from settings)
            db: Redis database number (default from settings)
            circuit_breaker: Optional circuit breaker instance
        """
        self.host = host or settings.redis_host
        self.port = port or settings.redis_port
        self.db = db or settings.redis_db

        # Create connection pool
        self.pool = redis.ConnectionPool(
            host=self.host,
            port=self.port,
            db=self.db,
            decode_responses=True,
            max_connections=10,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True
        )

        self.redis = redis.Redis(connection_pool=self.pool)
        self.circuit_breaker = circuit_breaker or RedisCircuitBreaker()

        logger.info(
            f"Redis queue initialized: {self.host}:{self.port}/{self.db}"
        )

    async def publish(self, event_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Publish webhook to Redis queue.

        Args:
            event_payload: Raw webhook event from Shopee

        Returns:
            Dict with keys:
                - success (bool): Whether publish succeeded
                - queue_id (str): Unique message ID
                - fallback_used (bool): Whether circuit breaker forced fallback
                - error (str, optional): Error message if failed
        """
        # Check circuit breaker
        if not self.circuit_breaker.should_attempt_redis():
            logger.warning("Circuit breaker open, skipping Redis publish")
            return {
                "success": False,
                "fallback_used": True,
                "error": "Circuit breaker open"
            }

        try:
            start_time = time.time()

            # Generate unique queue ID
            timestamp = int(time.time())
            order_sn = event_payload.get("data", {}).get("ordersn", "unknown")
            queue_id = f"wh_{timestamp}_{order_sn}"

            # Build message with metadata
            message = {
                "id": queue_id,
                "payload": event_payload,
                "metadata": {
                    "enqueued_at": time.time(),
                    "retry_count": 0,
                    "max_retries": settings.redis_max_retries
                }
            }

            # Publish to queue (LPUSH = add to left/head)
            await self.redis.lpush(QUEUE_MAIN, json.dumps(message))

            # Update stats
            await self._update_stats("total_enqueued", 1)

            latency_ms = (time.time() - start_time) * 1000

            logger.info(
                f"Published to Redis queue: id={queue_id}, "
                f"latency={latency_ms:.1f}ms"
            )

            # Record success in circuit breaker
            self.circuit_breaker.record_success()

            return {
                "success": True,
                "queue_id": queue_id,
                "fallback_used": False,
                "latency_ms": latency_ms
            }

        except redis.ConnectionError as e:
            logger.error(f"Redis connection error: {e}")
            self.circuit_breaker.record_failure()
            return {
                "success": False,
                "fallback_used": True,
                "error": f"Connection error: {e}"
            }

        except redis.TimeoutError as e:
            logger.error(f"Redis timeout: {e}")
            self.circuit_breaker.record_failure()
            return {
                "success": False,
                "fallback_used": True,
                "error": f"Timeout: {e}"
            }

        except Exception as e:
            logger.error(f"Unexpected error publishing to Redis: {e}", exc_info=True)
            self.circuit_breaker.record_failure()
            return {
                "success": False,
                "fallback_used": True,
                "error": str(e)
            }

    async def health_check(self) -> bool:
        """Check Redis connectivity.

        Returns:
            True if Redis is reachable, False otherwise
        """
        try:
            await self.redis.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    async def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics.

        Returns:
            Dict with queue metrics:
                - queue_depth: Number of messages in main queue
                - total_enqueued: Total messages published
                - total_processed: Total messages processed by workers
                - total_failed: Total messages moved to DLQ
                - dlq_depth: Number of messages in dead letter queue
                - circuit_breaker: Circuit breaker state
        """
        try:
            # Get queue depths
            queue_depth = await self.redis.llen(QUEUE_MAIN)
            dlq_depth = await self.redis.llen(QUEUE_DLQ)

            # Get stats hash
            stats_hash = await self.redis.hgetall(QUEUE_STATS)

            return {
                "queue_depth": queue_depth,
                "dlq_depth": dlq_depth,
                "total_enqueued": int(stats_hash.get("total_enqueued", 0)),
                "total_processed": int(stats_hash.get("total_processed", 0)),
                "total_failed": int(stats_hash.get("total_failed", 0)),
                "circuit_breaker": self.circuit_breaker.get_state()
            }

        except Exception as e:
            logger.error(f"Error getting queue stats: {e}")
            return {
                "error": str(e),
                "circuit_breaker": self.circuit_breaker.get_state()
            }

    async def _update_stats(self, field: str, increment: int = 1):
        """Update statistics in Redis hash.

        Args:
            field: Field name in stats hash
            increment: Amount to increment (default 1)
        """
        try:
            await self.redis.hincrby(QUEUE_STATS, field, increment)
        except Exception as e:
            logger.warning(f"Failed to update stats {field}: {e}")

    async def close(self):
        """Close Redis connection pool."""
        try:
            await self.redis.close()
            await self.pool.disconnect()
            logger.info("Redis queue connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")


# Global queue instance
_redis_queue: Optional[RedisWebhookQueue] = None


def get_redis_queue() -> RedisWebhookQueue:
    """Get or create global Redis queue instance.

    Returns:
        RedisWebhookQueue instance
    """
    global _redis_queue
    if _redis_queue is None:
        _redis_queue = RedisWebhookQueue()
    return _redis_queue


async def close_redis_queue():
    """Close global Redis queue instance."""
    global _redis_queue
    if _redis_queue is not None:
        await _redis_queue.close()
        _redis_queue = None
