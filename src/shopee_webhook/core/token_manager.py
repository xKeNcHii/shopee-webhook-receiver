"""Token management for Shopee API authentication."""

import json
import time
from pathlib import Path
from typing import Dict, Optional

from shopee_webhook.core.logger import setup_logger

logger = setup_logger(__name__)

TOKEN_FILE = Path("/app/config/shopee_tokens.json")

# In-memory token cache
_token_cache = {"tokens": None, "last_load_time": 0}


def save_tokens(tokens: Dict[str, any]) -> bool:
    """Save tokens to file and update cache."""
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)

        # Update cache
        _token_cache["tokens"] = tokens
        _token_cache["last_load_time"] = time.time()
        logger.info("Tokens saved and cached")
        return True
    except Exception as e:
        logger.error(f"Failed to save tokens: {e}")
        return False


def load_tokens() -> Optional[Dict[str, any]]:
    """Load tokens from cache if valid, otherwise from file."""
    # Check if cache has valid tokens
    if _token_cache["tokens"] and time.time() < _token_cache["tokens"].get("access_token_expires_at", 0):
        logger.debug("Using cached tokens")
        return _token_cache["tokens"]

    # Load from file
    try:
        if TOKEN_FILE.exists():
            with open(TOKEN_FILE, "r") as f:
                tokens = json.load(f)
                _token_cache["tokens"] = tokens
                _token_cache["last_load_time"] = time.time()
                logger.debug("Loaded tokens from file")
                return tokens
        return None
    except Exception as e:
        logger.error(f"Failed to load tokens: {e}")
        return None


def is_token_expired(access_token_expires_at: float) -> bool:
    """Check if token is expired (with 5 minute buffer)."""
    return time.time() >= (access_token_expires_at - 300)
