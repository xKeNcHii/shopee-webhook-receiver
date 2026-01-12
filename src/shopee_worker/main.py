"""Processor service entry point."""

import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)


if __name__ == "__main__":
    """Run the processor service."""
    port = int(os.getenv("PROCESSOR_PORT", 9000))
    reload = os.getenv("RELOAD", "false").lower() == "true"

    uvicorn.run(
        "shopee_worker.server.app:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )
