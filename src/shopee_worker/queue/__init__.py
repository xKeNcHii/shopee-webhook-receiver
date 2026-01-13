"""Worker management interface for Redis consumer workers.

Orchestrates multiple concurrent workers for parallel webhook processing.
"""

import os
import asyncio
from typing import List, Tuple

import redis.asyncio as redis

from shopee_api.core.logger import setup_logger
from shopee_worker.services.webhook_processor import WebhookProcessor
from shopee_worker.queue.redis_consumer import RedisWebhookConsumer
from shopee_api.config.settings import settings

logger = setup_logger(__name__)


def create_redis_pool() -> redis.ConnectionPool:
    """Create Redis connection pool for workers.

    Returns:
        Configured Redis connection pool
    """
    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))

    pool = redis.ConnectionPool(
        host=host,
        port=port,
        db=db,
        decode_responses=True,
        max_connections=10,  # Shared across all workers in process
        socket_timeout=settings.redis_brpop_timeout,
        socket_connect_timeout=settings.redis_brpop_timeout,
        retry_on_timeout=True
    )

    logger.info(f"Redis connection pool created: {host}:{port}/{db}")
    return pool


async def start_consumer_workers(
    processor: WebhookProcessor,
    num_workers: int = 3
) -> List[Tuple[RedisWebhookConsumer, asyncio.Task]]:
    """Start N concurrent consumer workers.

    Creates worker instances and launches them as async tasks.
    All workers share a single Redis connection pool for efficiency.

    Args:
        processor: WebhookProcessor instance for processing logic
        num_workers: Number of concurrent workers to start

    Returns:
        List of (consumer, task) tuples for graceful shutdown
    """
    logger.info("=" * 60)
    logger.info(f"Starting {num_workers} Redis consumer workers...")
    logger.info("=" * 60)

    # Create shared connection pool
    redis_pool = create_redis_pool()

    workers = []

    for i in range(num_workers):
        # Create consumer instance
        consumer = RedisWebhookConsumer(
            redis_pool=redis_pool,
            webhook_processor=processor,
            worker_id=i + 1
        )

        # Launch as async task
        task = asyncio.create_task(consumer.start())
        workers.append((consumer, task))

        logger.info(f"✓ Worker-{i+1} launched")

    logger.info("=" * 60)
    logger.info(f"All {num_workers} workers started successfully")
    logger.info("=" * 60)

    return workers


async def stop_consumer_workers(
    workers: List[Tuple[RedisWebhookConsumer, asyncio.Task]]
):
    """Gracefully stop all consumer workers.

    Steps:
    1. Signal all workers to stop (set is_running = False)
    2. Wait for all workers to finish current messages
    3. Cancel any stuck tasks

    Args:
        workers: List of (consumer, task) tuples from start_consumer_workers
    """
    if not workers:
        logger.info("No workers to stop")
        return

    logger.info("=" * 60)
    logger.info(f"Stopping {len(workers)} Redis consumer workers...")
    logger.info("=" * 60)

    # Signal all workers to stop
    for consumer, _ in workers:
        await consumer.stop()

    logger.info("All workers signaled to stop, waiting for completion...")

    # Wait for all workers to finish current messages
    tasks = [task for _, task in workers]

    try:
        # Wait with timeout (should complete quickly since workers were signaled)
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=30.0
        )
        logger.info("✓ All workers stopped gracefully")

    except asyncio.TimeoutError:
        logger.warning("Timeout waiting for workers, cancelling tasks...")

        # Cancel stuck tasks
        for task in tasks:
            if not task.done():
                task.cancel()

        # Wait for cancellation
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("✓ All workers cancelled")

    # Log final statistics
    for consumer, _ in workers:
        stats = consumer.get_stats()
        logger.info(
            f"Worker-{stats['worker_id']} stats: "
            f"processed={stats['messages_processed']}, "
            f"failed={stats['messages_failed']}, "
            f"avg_time={stats['avg_processing_time']:.2f}s"
        )

    logger.info("=" * 60)
    logger.info("All workers stopped")
    logger.info("=" * 60)


async def get_workers_stats(
    workers: List[Tuple[RedisWebhookConsumer, asyncio.Task]]
) -> List[dict]:
    """Get statistics from all workers.

    Args:
        workers: List of (consumer, task) tuples

    Returns:
        List of worker stats dicts
    """
    return [consumer.get_stats() for consumer, _ in workers]
