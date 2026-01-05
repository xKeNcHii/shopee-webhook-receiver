"""FastAPI application setup and configuration."""

import asyncio
import os
import signal
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shopee_webhook.config.settings import settings
from shopee_webhook.core.logger import setup_logger

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

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import and include routers
    from shopee_webhook.server import routes

    app.include_router(routes.router)

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
