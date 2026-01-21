"""
Reconciliation Scheduler using APScheduler.

Manages scheduled reconciliation jobs:
- Hourly sync: Every SYNC_INTERVAL_HOURS
- Daily full sync: At DAILY_SYNC_HOUR (3 AM by default)
"""

from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from shopee_api.core.logger import setup_logger
from shopee_api.config.constants import SYNC_INTERVAL_HOURS, DAILY_SYNC_HOUR
from shopee_worker.services.reconciliation_service import ReconciliationService

logger = setup_logger(__name__)


class ReconciliationScheduler:
    """Manages scheduled reconciliation jobs using APScheduler."""

    def __init__(self, reconciliation_service: ReconciliationService):
        self.service = reconciliation_service
        self.scheduler = AsyncIOScheduler()
        self._started = False

    async def start(self, run_startup_sync: bool = True):
        """
        Start scheduler with configured jobs.

        Args:
            run_startup_sync: Whether to run startup catch-up sync immediately
        """
        if self._started:
            logger.warning("Scheduler already started")
            return

        # Add hourly sync job
        self.scheduler.add_job(
            self._run_scheduled_sync,
            IntervalTrigger(hours=SYNC_INTERVAL_HOURS),
            id="scheduled_sync",
            name="Hourly Order Reconciliation",
            replace_existing=True,
        )
        logger.info(f"Added scheduled sync job (every {SYNC_INTERVAL_HOURS} hour(s))")

        # Add daily full sync job
        self.scheduler.add_job(
            self._run_daily_sync,
            CronTrigger(hour=DAILY_SYNC_HOUR, minute=0),
            id="daily_full_sync",
            name="Daily Full Reconciliation",
            replace_existing=True,
        )
        logger.info(f"Added daily full sync job (at {DAILY_SYNC_HOUR:02d}:00)")

        # Start the scheduler
        self.scheduler.start()
        self._started = True
        logger.info("Reconciliation scheduler started")

        # Run startup catch-up sync if requested
        if run_startup_sync:
            logger.info("Running startup catch-up sync...")
            try:
                result = await self.service.startup_catchup_sync()
                if result.success:
                    logger.info(
                        f"Startup sync completed: {result.orders_processed} orders processed"
                    )
                else:
                    logger.warning(f"Startup sync had issues: {result.errors}")
            except Exception as e:
                logger.error(f"Startup sync failed: {e}", exc_info=True)

    async def stop(self):
        """Gracefully stop scheduler."""
        if not self._started:
            return

        self.scheduler.shutdown(wait=True)
        self._started = False
        logger.info("Reconciliation scheduler stopped")

    async def _run_scheduled_sync(self):
        """Wrapper for scheduled sync with error handling."""
        try:
            logger.info("Scheduled sync triggered")
            result = await self.service.scheduled_sync()
            if result.success:
                logger.info(f"Scheduled sync completed: {result.orders_processed} orders")
            else:
                logger.warning(f"Scheduled sync had issues: {result.errors}")
        except Exception as e:
            logger.error(f"Scheduled sync failed: {e}", exc_info=True)

    async def _run_daily_sync(self):
        """Wrapper for daily sync with error handling."""
        try:
            logger.info("Daily full sync triggered")
            result = await self.service.daily_full_sync()
            if result.success:
                logger.info(f"Daily sync completed: {result.orders_processed} orders")
            else:
                logger.warning(f"Daily sync had issues: {result.errors}")
        except Exception as e:
            logger.error(f"Daily full sync failed: {e}", exc_info=True)

    def get_next_run_times(self) -> dict:
        """Get next scheduled run times for dashboard."""
        result = {}

        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            if next_run:
                result[job.id] = next_run.strftime("%Y-%m-%d %H:%M:%S")
            else:
                result[job.id] = None

        return result

    def get_next_scheduled_sync(self) -> Optional[str]:
        """Get the next scheduled sync time as formatted string."""
        job = self.scheduler.get_job("scheduled_sync")
        if job and job.next_run_time:
            return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
        return None

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._started and self.scheduler.running
