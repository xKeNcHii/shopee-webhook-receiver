"""
Reconciliation Service for Shopee Order Sync.

Handles order reconciliation between Shopee API and Google Sheets storage.
Provides startup catch-up, scheduled sync, daily full sync, and manual sync.
"""

import asyncio
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import redis.asyncio as aioredis

from shopee_api.core.logger import setup_logger
from shopee_api.config.constants import (
    SYNC_INTERVAL_HOURS,
    HISTORICAL_DAYS,
    SYNC_OVERLAP_HOURS,
    ORDER_DETAIL_BATCH_SIZE,
    SYNC_TIMEOUT_SECONDS,
    API_CALL_DELAY_SECONDS,
    TIMEZONE_OFFSET_HOURS,
    IGNORE_STATUSES,
)

logger = setup_logger(__name__)

# Redis keys for sync state
REDIS_LAST_SYNC = "shopee:reconciliation:last_sync_timestamp"
REDIS_LAST_FULL_SYNC = "shopee:reconciliation:last_full_sync_timestamp"
REDIS_SYNC_HISTORY = "shopee:reconciliation:sync_history"
REDIS_SYNC_LOCK = "shopee:reconciliation:sync_in_progress"


@dataclass
class SyncResult:
    """Result of a sync operation."""
    sync_type: str  # "startup", "scheduled", "daily", "manual"
    started_at: float
    completed_at: float
    time_from: int
    time_to: int
    orders_fetched: int
    orders_processed: int
    orders_skipped: int
    errors: List[str]
    success: bool


@dataclass
class SyncStatus:
    """Current sync status for dashboard."""
    last_sync_timestamp: Optional[float]
    last_sync_time_formatted: Optional[str]
    last_full_sync_timestamp: Optional[float]
    last_full_sync_time_formatted: Optional[str]
    next_scheduled_sync: Optional[str]
    sync_in_progress: bool
    sync_history: List[dict]


class ReconciliationService:
    """
    Handles order reconciliation between Shopee API and Google Sheets.

    Features:
    - Startup catch-up: Syncs orders since last known sync time
    - Scheduled sync: Every hour, fetches orders updated in last 2 hours
    - Daily full sync: All orders from last 7 days
    - Manual sync: Date range configurable via dashboard
    """

    def __init__(
        self,
        api_client,
        order_service,
        repository,
        redis_host: str = "redis",
        redis_port: int = 6379,
        redis_db: int = 0,
    ):
        self.api_client = api_client
        self.order_service = order_service
        self.repository = repository
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = await aioredis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True,
            )
        return self._redis

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    def _get_singapore_time(self, timestamp: Optional[float] = None) -> datetime:
        """Get datetime in Singapore timezone."""
        sg_tz = timezone(timedelta(hours=TIMEZONE_OFFSET_HOURS))
        if timestamp:
            return datetime.fromtimestamp(timestamp, tz=sg_tz)
        return datetime.now(sg_tz)

    def _format_timestamp(self, timestamp: Optional[float]) -> Optional[str]:
        """Format timestamp for display."""
        if not timestamp:
            return None
        dt = self._get_singapore_time(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    async def _acquire_sync_lock(self, timeout: int = SYNC_TIMEOUT_SECONDS) -> bool:
        """Acquire distributed lock for sync operation."""
        redis = await self._get_redis()
        acquired = await redis.set(
            REDIS_SYNC_LOCK,
            value=str(time.time()),
            nx=True,
            ex=timeout,
        )
        return bool(acquired)

    async def _release_sync_lock(self):
        """Release sync lock."""
        redis = await self._get_redis()
        await redis.delete(REDIS_SYNC_LOCK)

    async def _is_sync_in_progress(self) -> bool:
        """Check if a sync is currently in progress."""
        redis = await self._get_redis()
        return await redis.exists(REDIS_SYNC_LOCK) > 0

    async def _record_sync_result(self, result: SyncResult):
        """Record sync result to history list (max 10 entries)."""
        redis = await self._get_redis()

        entry = asdict(result)
        # Limit errors stored
        entry["errors"] = entry["errors"][:5]

        await redis.lpush(REDIS_SYNC_HISTORY, json.dumps(entry))
        await redis.ltrim(REDIS_SYNC_HISTORY, 0, 9)

        # Update last sync timestamp if successful
        if result.success:
            await redis.set(REDIS_LAST_SYNC, str(result.completed_at))
            if result.sync_type == "daily":
                await redis.set(REDIS_LAST_FULL_SYNC, str(result.completed_at))

    async def sync_orders_in_range(
        self,
        time_from: int,
        time_to: int,
        sync_type: str = "scheduled",
    ) -> SyncResult:
        """
        Core sync method that fetches and upserts orders within a time range.

        Steps:
        1. Acquire sync lock (prevent concurrent syncs)
        2. Fetch order list from Shopee API
        3. Batch fetch order details
        4. Process each order through existing flow
        5. Record sync result
        6. Release sync lock
        """
        started_at = time.time()
        orders_fetched = 0
        orders_processed = 0
        orders_skipped = 0
        errors = []

        logger.info(f"Starting {sync_type} sync from {self._format_timestamp(time_from)} to {self._format_timestamp(time_to)}")

        # Acquire lock
        if not await self._acquire_sync_lock():
            logger.warning("Sync already in progress, skipping")
            return SyncResult(
                sync_type=sync_type,
                started_at=started_at,
                completed_at=time.time(),
                time_from=time_from,
                time_to=time_to,
                orders_fetched=0,
                orders_processed=0,
                orders_skipped=0,
                errors=["Sync already in progress"],
                success=False,
            )

        try:
            # Step 1: Fetch order list
            order_list = await self.api_client.get_order_list(
                time_from=time_from,
                time_to=time_to,
                time_range_field="update_time",
            )
            orders_fetched = len(order_list)
            logger.info(f"Fetched {orders_fetched} orders from Shopee API")

            if orders_fetched == 0:
                logger.info("No orders to sync")
                result = SyncResult(
                    sync_type=sync_type,
                    started_at=started_at,
                    completed_at=time.time(),
                    time_from=time_from,
                    time_to=time_to,
                    orders_fetched=0,
                    orders_processed=0,
                    orders_skipped=0,
                    errors=[],
                    success=True,
                )
                await self._record_sync_result(result)
                return result

            # Step 2: Process orders in batches
            order_sns = [order.get("order_sn") for order in order_list if order.get("order_sn")]

            for i in range(0, len(order_sns), ORDER_DETAIL_BATCH_SIZE):
                batch = order_sns[i:i + ORDER_DETAIL_BATCH_SIZE]
                logger.info(f"Processing batch {i // ORDER_DETAIL_BATCH_SIZE + 1}: {len(batch)} orders")

                for order_sn in batch:
                    try:
                        # Find order status from list
                        order_info = next(
                            (o for o in order_list if o.get("order_sn") == order_sn),
                            {}
                        )
                        order_status = order_info.get("order_status", "")

                        # Skip ignored statuses
                        if order_status in IGNORE_STATUSES:
                            orders_skipped += 1
                            logger.debug(f"Skipping order {order_sn} with status {order_status}")
                            continue

                        # Fetch order details using order service
                        order_info = await self.order_service.fetch_order_details(order_sn)

                        if not order_info:
                            logger.warning(f"Failed to fetch order {order_sn}")
                            continue

                        # Extract items from order_data
                        order_data = order_info.get("order_data", {})
                        items = order_data.get("items", [])

                        if not items:
                            logger.debug(f"No items found for order {order_sn}")
                            continue

                        # Upsert to repository (Google Sheets)
                        success = await self.repository.upsert_order_items(items)
                        if success:
                            orders_processed += 1
                        else:
                            errors.append(f"Failed to upsert order {order_sn}")

                        # Rate limiting delay
                        await asyncio.sleep(API_CALL_DELAY_SECONDS)

                    except Exception as e:
                        error_msg = f"Error processing order {order_sn}: {str(e)}"
                        logger.error(error_msg)
                        errors.append(error_msg)

            success = len(errors) == 0 or orders_processed > 0
            result = SyncResult(
                sync_type=sync_type,
                started_at=started_at,
                completed_at=time.time(),
                time_from=time_from,
                time_to=time_to,
                orders_fetched=orders_fetched,
                orders_processed=orders_processed,
                orders_skipped=orders_skipped,
                errors=errors,
                success=success,
            )

            await self._record_sync_result(result)

            logger.info(
                f"Sync completed: {orders_processed}/{orders_fetched} processed, "
                f"{orders_skipped} skipped, {len(errors)} errors"
            )

            return result

        except Exception as e:
            error_msg = f"Sync failed: {str(e)}"
            logger.error(error_msg, exc_info=True)

            result = SyncResult(
                sync_type=sync_type,
                started_at=started_at,
                completed_at=time.time(),
                time_from=time_from,
                time_to=time_to,
                orders_fetched=orders_fetched,
                orders_processed=orders_processed,
                orders_skipped=orders_skipped,
                errors=[error_msg],
                success=False,
            )

            await self._record_sync_result(result)
            return result

        finally:
            await self._release_sync_lock()

    async def startup_catchup_sync(self) -> SyncResult:
        """
        Called on worker startup to catch up on missed orders.

        Logic:
        1. Read last_sync_timestamp from Redis
        2. If exists: sync from last_sync to now
        3. If not exists: sync last HISTORICAL_DAYS
        """
        logger.info("Running startup catch-up sync")

        redis = await self._get_redis()
        last_sync = await redis.get(REDIS_LAST_SYNC)

        now = int(time.time())

        if last_sync:
            time_from = int(float(last_sync))
            logger.info(f"Last sync was at {self._format_timestamp(time_from)}, catching up")
        else:
            # No previous sync - sync last HISTORICAL_DAYS
            time_from = now - (HISTORICAL_DAYS * 24 * 60 * 60)
            logger.info(f"No previous sync found, syncing last {HISTORICAL_DAYS} days")

        return await self.sync_orders_in_range(
            time_from=time_from,
            time_to=now,
            sync_type="startup",
        )

    async def scheduled_sync(self) -> SyncResult:
        """
        Called every SYNC_INTERVAL_HOURS.

        Logic:
        1. Calculate time range: (now - SYNC_OVERLAP_HOURS) to now
        2. Run sync_orders_in_range
        """
        logger.info("Running scheduled sync")

        now = int(time.time())
        time_from = now - (SYNC_OVERLAP_HOURS * 60 * 60)

        return await self.sync_orders_in_range(
            time_from=time_from,
            time_to=now,
            sync_type="scheduled",
        )

    async def daily_full_sync(self) -> SyncResult:
        """
        Called once per day at DAILY_SYNC_HOUR.

        Logic:
        1. Calculate time range: (now - HISTORICAL_DAYS) to now
        2. Run sync_orders_in_range with sync_type="daily"
        """
        logger.info("Running daily full sync")

        now = int(time.time())
        time_from = now - (HISTORICAL_DAYS * 24 * 60 * 60)

        return await self.sync_orders_in_range(
            time_from=time_from,
            time_to=now,
            sync_type="daily",
        )

    async def manual_sync(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> SyncResult:
        """
        Called from dashboard with user-specified date range.

        Validation:
        - end_date cannot be in the future
        - start_date cannot be more than 30 days ago
        - Range cannot exceed 7 days per sync
        """
        logger.info(f"Running manual sync from {start_date} to {end_date}")

        now = datetime.now(timezone.utc)

        # Validation
        if end_date > now:
            end_date = now

        max_past = now - timedelta(days=30)
        if start_date < max_past:
            start_date = max_past

        # Convert to timestamps
        time_from = int(start_date.timestamp())
        time_to = int(end_date.timestamp())

        return await self.sync_orders_in_range(
            time_from=time_from,
            time_to=time_to,
            sync_type="manual",
        )

    async def get_sync_status(self, next_scheduled: Optional[str] = None) -> SyncStatus:
        """
        Returns current sync state for dashboard.

        Args:
            next_scheduled: Next scheduled sync time (from scheduler)
        """
        redis = await self._get_redis()

        # Get timestamps
        last_sync = await redis.get(REDIS_LAST_SYNC)
        last_full_sync = await redis.get(REDIS_LAST_FULL_SYNC)

        last_sync_ts = float(last_sync) if last_sync else None
        last_full_sync_ts = float(last_full_sync) if last_full_sync else None

        # Check if sync in progress
        sync_in_progress = await self._is_sync_in_progress()

        # Get history
        history_raw = await redis.lrange(REDIS_SYNC_HISTORY, 0, 9)
        sync_history = []
        for entry in history_raw:
            try:
                sync_history.append(json.loads(entry))
            except Exception:
                continue

        return SyncStatus(
            last_sync_timestamp=last_sync_ts,
            last_sync_time_formatted=self._format_timestamp(last_sync_ts),
            last_full_sync_timestamp=last_full_sync_ts,
            last_full_sync_time_formatted=self._format_timestamp(last_full_sync_ts),
            next_scheduled_sync=next_scheduled,
            sync_in_progress=sync_in_progress,
            sync_history=sync_history,
        )
