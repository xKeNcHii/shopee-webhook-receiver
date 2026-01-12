"""Shopee Webhook Receiver - Main Entry Point."""

import os

from shopee_api.server.app import create_app

# Create FastAPI application
app = create_app()

if __name__ == "__main__":
    import uvicorn

    # Get configuration from environment
    reload = os.getenv("RELOAD", "false").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    # Run uvicorn with graceful shutdown configuration
    # - timeout_graceful_shutdown: Allow time for app to gracefully shutdown
    #   (app will wait indefinitely for pending tasks, this is uvicorn's outer timeout)
    # - timeout_keep_alive: Keep-alive timeout for persistent connections
    uvicorn.run(
        "shopee_api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=reload,
        log_level=log_level,
        timeout_graceful_shutdown=120,  # 120 seconds max for uvicorn to wait
        timeout_keep_alive=5,  # 5 seconds keep-alive
        access_log=False,  # Disable uvicorn access log (we use structured logging)
    )
