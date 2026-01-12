"""FastAPI application setup and configuration."""

import asyncio
import os
import signal
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shopee_api.config.settings import settings
from shopee_api.core.logger import setup_logger

logger = setup_logger(__name__)

# Global variables for resource management
_pending_tasks = set()


def track_task(task: asyncio.Task) -> None:
    """
    Track a background task for graceful shutdown.

    Args:
        task: The asyncio Task to track
    """
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Shopee Webhook Forwarder",
        version="2.0.0",
        description="Receives Shopee webhooks, fetches order details, and forwards to custom service",
    )

    # Initialize GlitchTip error monitoring (Sentry-compatible)
    if settings.glitchtip_dsn:
        try:
            import logging
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.logging import LoggingIntegration

            sentry_sdk.init(
                dsn=settings.glitchtip_dsn,
                environment=settings.environment,
                integrations=[
                    FastApiIntegration(transaction_style="endpoint"),
                    LoggingIntegration(
                        level=None,  # Capture all log levels as breadcrumbs
                        event_level=logging.ERROR  # Send ERROR logs as events
                    ),
                ],
                traces_sample_rate=0.1,  # 10% of transactions for performance monitoring
                profiles_sample_rate=0.0,  # Disable profiling
                send_default_pii=False,  # Don't send personally identifiable information
            )
            logger.info("GlitchTip error monitoring initialized")
        except Exception as e:
            logger.error(f"Failed to initialize GlitchTip: {e}")

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Import and include routers
    from shopee_api.server import routes, dashboard_routes

    app.include_router(routes.router)
    app.include_router(dashboard_routes.router)

    # Startup handler
    @app.on_event("startup")
    async def startup_handler():
        """
        Initialize resources on application startup.

        Starts the Telegram message queue worker for rate-limited sending.
        """
        logger.info("Starting application resources...")

        try:
            # Start Telegram queue worker
            from shopee_api.integrations.telegram_queue import start_queue_worker
            await start_queue_worker()
            logger.info("Telegram queue worker started successfully")
        except Exception as e:
            logger.error(f"Error starting Telegram queue worker: {e}", exc_info=True)

        logger.info("Application startup completed")

    # Graceful shutdown handler
    @app.on_event("shutdown")
    async def shutdown_handler():
        """
        Gracefully shut down all resources.

        This handler is triggered when the application receives a shutdown signal
        (SIGTERM from Docker, or application termination). It ensures:
        1. All pending background tasks complete before shutdown
        2. No data loss or incomplete operations

        Will wait indefinitely for all tasks to complete.
        """
        logger.info("Starting graceful shutdown...")

        try:
            # Stop Telegram queue worker
            try:
                from shopee_api.integrations.telegram_queue import stop_queue_worker
                logger.info("Stopping Telegram queue worker...")
                await stop_queue_worker()
                logger.info("Telegram queue worker stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping Telegram queue worker: {e}", exc_info=True)

            # Wait for all pending tasks to complete (no timeout)
            if _pending_tasks:
                logger.info(
                    f"Waiting for {len(_pending_tasks)} pending tasks to complete "
                    "(no timeout - will wait as long as needed)..."
                )
                try:
                    await asyncio.gather(*_pending_tasks, return_exceptions=True)
                    logger.info(
                        f"All {len(_pending_tasks)} pending tasks completed successfully"
                    )
                except Exception as e:
                    logger.error(
                        f"Error while waiting for tasks to complete: {e}", exc_info=True
                    )
            else:
                logger.debug("No pending tasks to wait for")

            logger.info("Graceful shutdown completed successfully")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)

    return app
