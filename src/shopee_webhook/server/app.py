"""FastAPI application setup and configuration."""

import asyncio
import os
import signal
from fastapi import FastAPI, Depends
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from shopee_webhook.config.settings import settings
from shopee_webhook.core.logger import setup_logger
from shopee_webhook.db import get_engine, get_session_factory, init_db

logger = setup_logger(__name__)

# Global variables for resource management
_engine = None
_session_factory = None
_pending_tasks = set()


async def get_db_session() -> AsyncSession:
    """Dependency for getting database session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")

    async with _session_factory() as session:
        yield session


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
        title="Shopee Webhook Receiver",
        version="1.0.0",
        description="Receives and logs Shopee webhook notifications in real-time",
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import router AFTER defining get_db_session
    from shopee_webhook.server import routes

    # Include routers
    app.include_router(routes.router)

    # Override the stub dependency with the actual get_db_session
    app.dependency_overrides[routes.get_db_session_stub] = get_db_session

    # Database initialization on startup
    @app.on_event("startup")
    async def startup_db():
        """Initialize database on application startup."""
        global _engine, _session_factory

        try:
            logger.info(f"Initializing database: {settings.database_url}")
            await init_db(settings.database_url)

            _engine = get_engine(settings.database_url)
            _session_factory = get_session_factory(_engine)

            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise

    # Graceful shutdown handler
    @app.on_event("shutdown")
    async def shutdown_handler():
        """
        Gracefully shut down all resources.

        This handler is triggered when the application receives a shutdown signal
        (SIGTERM from Docker, or application termination). It ensures:
        1. All pending background tasks complete before shutdown
        2. Database connections are properly closed
        3. No data loss or incomplete operations

        Will wait indefinitely for all tasks to complete.
        """
        logger.info("Starting graceful shutdown...")

        try:
            # 1. Wait for all pending tasks to complete (no timeout)
            if _pending_tasks:
                logger.info(
                    f"Waiting for {len(_pending_tasks)} pending tasks to complete "
                    "(no timeout - will wait as long as needed)..."
                )
                try:
                    await asyncio.gather(*_pending_tasks, return_exceptions=True)
                    logger.info(f"All {len(_pending_tasks)} pending tasks completed successfully")
                except Exception as e:
                    logger.error(f"Error while waiting for tasks to complete: {e}", exc_info=True)
            else:
                logger.debug("No pending tasks to wait for")

            # 2. Close database connections
            if _engine:
                logger.info("Closing database connections...")
                try:
                    await _engine.dispose()
                    logger.info("Database connections closed successfully")
                except Exception as e:
                    logger.error(f"Error closing database connections: {e}")

            logger.info("Graceful shutdown completed successfully")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)

    return app
