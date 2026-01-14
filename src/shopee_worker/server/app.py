"""Processor FastAPI application."""

import os
from fastapi import FastAPI
from shopee_worker.server.routes import router, set_webhook_processor
from shopee_worker.services.webhook_processor import WebhookProcessor
from shopee_worker.repositories.sheets_repository import GoogleSheetsRepository

# Import SHARED modules from forwarder
from shopee_api.api.client import ShopeeAPIClient
from shopee_api.services.order_service import OrderService
from shopee_api.core.logger import setup_logger

logger = setup_logger(__name__)


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        Configured FastAPI app instance
    """
    app = FastAPI(
        title="Shopee Order Processor",
        description="Processes Shopee webhooks and stores in Google Sheets",
        version="1.0.0"
    )

    # Initialize GlitchTip error monitoring
    from shopee_api.config.settings import settings
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
                traces_sample_rate=0.1,
                profiles_sample_rate=0.0,
                send_default_pii=False,
            )
            logger.info("GlitchTip error monitoring initialized")
        except Exception as e:
            logger.error(f"Failed to initialize GlitchTip: {e}")

    @app.on_event("startup")
    async def startup():
        """Initialize services and repositories on startup.

        Steps:
        1. Initialize SHARED Shopee API client (from forwarder)
        2. Initialize SHARED order service (from forwarder)
        3. Initialize NEW Google Sheets repository
        4. Initialize NEW webhook processor
        5. Set global processor instance
        """
        try:
            logger.info("=" * 60)
            logger.info("Starting Shopee Order Processor...")
            logger.info("=" * 60)

            # Initialize SHARED Shopee API client
            logger.info("Initializing Shopee API client...")
            api_client = ShopeeAPIClient(
                partner_id=int(os.getenv("PARTNER_ID")),
                partner_key=os.getenv("PARTNER_KEY"),
                shop_id=int(os.getenv("SHOP_ID")),
                access_token=os.getenv("ACCESS_TOKEN"),
                refresh_token=os.getenv("REFRESH_TOKEN"),
            )
            logger.info("✓ Shopee API client initialized")

            # Initialize SHARED order service
            logger.info("Initializing order service...")
            order_service = OrderService(api_client)
            logger.info("✓ Order service initialized")

            # Initialize NEW Google Sheets repository
            logger.info("Initializing Google Sheets repository...")
            credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/google_credentials.json")
            spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
            sheet_name = os.getenv("GOOGLE_SHEET_NAME")  # Optional: specific sheet name

            if not spreadsheet_id:
                logger.error("GOOGLE_SPREADSHEET_ID not set in environment variables!")
                raise ValueError("GOOGLE_SPREADSHEET_ID is required")

            repository = GoogleSheetsRepository(
                credentials_path=credentials_path,
                spreadsheet_id=spreadsheet_id,
                sheet_name=sheet_name  # Will use first sheet if None
            )
            logger.info("✓ Google Sheets repository initialized")

            # Initialize NEW webhook processor
            logger.info("Initializing webhook processor...")
            processor = WebhookProcessor(
                order_service=order_service,
                repository=repository
            )
            logger.info("✓ Webhook processor initialized")

            # Set global processor instance
            set_webhook_processor(processor)

            # Start Redis consumer workers (if enabled)
            redis_enabled = os.getenv("REDIS_ENABLED", "true").lower() == "true"
            if redis_enabled:
                from shopee_worker.queue import start_consumer_workers

                num_workers = int(os.getenv("REDIS_NUM_WORKERS", "3"))
                app.state.worker_tasks = await start_consumer_workers(
                    processor=processor,
                    num_workers=num_workers
                )
                logger.info(f"✓ Started {num_workers} Redis consumer workers")
            else:
                logger.info("Redis consumers disabled, using HTTP endpoint only")
                app.state.worker_tasks = None

            logger.info("=" * 60)
            logger.info("Shopee Order Processor started successfully!")
            logger.info(f"Storage: Google Sheets (ID: {spreadsheet_id[:20]}...)")
            if sheet_name:
                logger.info(f"Target Sheet: {sheet_name}")
            else:
                logger.info("Target Sheet: First sheet (default)")
            if redis_enabled:
                logger.info(f"Processing Mode: Redis Queue ({num_workers} workers)")
            else:
                logger.info("Processing Mode: HTTP endpoint only")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Failed to start processor: {e}", exc_info=True)
            raise

    @app.on_event("shutdown")
    async def shutdown():
        """Graceful shutdown: wait for workers to complete."""
        logger.info("=" * 60)
        logger.info("Shutting down Shopee Order Processor...")
        logger.info("=" * 60)

        # Stop Redis workers gracefully
        if hasattr(app.state, "worker_tasks") and app.state.worker_tasks:
            from shopee_worker.queue import stop_consumer_workers
            logger.info("Waiting for workers to finish current messages...")
            await stop_consumer_workers(app.state.worker_tasks)
            logger.info("✓ All workers stopped")

        logger.info("=" * 60)
        logger.info("Shutdown completed")
        logger.info("=" * 60)

    # Include routes
    app.include_router(router)

    return app


# Create app instance
app = create_app()
