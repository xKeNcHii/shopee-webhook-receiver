"""
Runtime Configuration Manager

Manages in-memory configuration with JSON file persistence.
Configuration changes persist across container restarts without needing rebuild.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from shopee_api.core.logger import setup_logger

logger = setup_logger(__name__)

# Configuration file path (in config/ directory, auto-created)
CONFIG_FILE = Path("/app/config/runtime_config.json")


class RuntimeConfig:
    """Manages runtime configuration with JSON file persistence."""

    def __init__(self):
        """Initialize runtime config, loading from file if exists."""
        self._config = self._load_config()
        logger.info("Runtime configuration initialized")

    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from JSON file.

        If file doesn't exist, initialize with current environment variables.

        Returns:
            Configuration dictionary
        """
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.info(f"Loaded runtime config from {CONFIG_FILE}")
                return config
            except Exception as e:
                logger.error(f"Failed to load runtime config: {e}")
                return self._initialize_from_env()

        logger.info("No runtime config file found, initializing from environment variables")
        return self._initialize_from_env()

    def _initialize_from_env(self) -> Dict[str, Any]:
        """
        Initialize config from environment variables.

        This copies the current .env settings into runtime config,
        so the dashboard shows the actual current configuration.
        """
        try:
            from shopee_api.config.settings import settings

            config = {
                "telegram": {},
                "forwarder": {},
                "glitchtip": {}
            }

            # Initialize Telegram config from .env if available
            if settings.telegram_bot_token and settings.telegram_chat_id:
                config["telegram"] = {
                    "enabled": True,
                    "bot_token": settings.telegram_bot_token,
                    "chat_id": settings.telegram_chat_id,
                    "initialized_from": "environment",
                    "updated_at": datetime.utcnow().isoformat()
                }
                logger.info("Initialized Telegram config from environment variables")

            # Initialize Forwarder config from .env if available
            if settings.forward_webhook_url:
                config["forwarder"] = {
                    "enabled": True,
                    "url": settings.forward_webhook_url,
                    "initialized_from": "environment",
                    "updated_at": datetime.utcnow().isoformat()
                }
                logger.info("Initialized Forwarder config from environment variables")

            # Initialize GlitchTip config from .env if available
            if settings.glitchtip_dsn:
                config["glitchtip"] = {
                    "enabled": True,
                    "dsn": settings.glitchtip_dsn,
                    "initialized_from": "environment",
                    "updated_at": datetime.utcnow().isoformat()
                }
                logger.info("Initialized GlitchTip config from environment variables")

            # Save to file for persistence
            self._config = config
            self._save_config()

            return config
        except Exception as e:
            logger.error(f"Failed to initialize from env: {e}")
            return {"telegram": {}, "forwarder": {}, "glitchtip": {}}

    def _save_config(self):
        """Save configuration to JSON file."""
        try:
            # Ensure config directory exists
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved runtime config to {CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Failed to save runtime config: {e}")

    def update_telegram(self, enabled: bool, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Update Telegram configuration and persist to file.

        Args:
            enabled: Whether Telegram notifications are enabled
            bot_token: Telegram bot token (optional, keeps existing if not provided)
            chat_id: Telegram chat ID (optional, keeps existing if not provided)
        """
        # Preserve existing values if not provided
        existing = self._config.get("telegram", {})

        self._config["telegram"] = {
            "enabled": enabled,
            "bot_token": bot_token if bot_token is not None else existing.get("bot_token"),
            "chat_id": chat_id if chat_id is not None else existing.get("chat_id"),
            "updated_at": datetime.utcnow().isoformat()
        }

        self._save_config()
        logger.info(f"Updated Telegram config: enabled={enabled}")

    def update_forwarder(self, enabled: bool, url: Optional[str] = None):
        """
        Update Forwarder configuration and persist to file.

        Args:
            enabled: Whether webhook forwarding is enabled
            url: Forwarder URL (optional, keeps existing if not provided)
        """
        # Preserve existing values if not provided
        existing = self._config.get("forwarder", {})

        self._config["forwarder"] = {
            "enabled": enabled,
            "url": url if url is not None else existing.get("url"),
            "updated_at": datetime.utcnow().isoformat()
        }

        self._save_config()
        logger.info(f"Updated Forwarder config: enabled={enabled}")

    def get_telegram_config(self) -> Dict[str, Any]:
        """
        Get current Telegram configuration.

        Returns:
            Telegram config dictionary (enabled, bot_token, chat_id)
        """
        return self._config.get("telegram", {})

    def get_forwarder_config(self) -> Dict[str, Any]:
        """
        Get current Forwarder configuration.

        Returns:
            Forwarder config dictionary (enabled, url)
        """
        return self._config.get("forwarder", {})

    def update_glitchtip(self, enabled: bool, dsn: Optional[str] = None):
        """
        Update GlitchTip configuration and persist to file.

        Args:
            enabled: Whether GlitchTip error monitoring is enabled
            dsn: GlitchTip DSN (optional, keeps existing if not provided)
        """
        # Preserve existing values if not provided
        existing = self._config.get("glitchtip", {})

        self._config["glitchtip"] = {
            "enabled": enabled,
            "dsn": dsn if dsn is not None else existing.get("dsn"),
            "updated_at": datetime.utcnow().isoformat()
        }

        self._save_config()
        logger.info(f"Updated GlitchTip config: enabled={enabled}")

    def get_glitchtip_config(self) -> Dict[str, Any]:
        """
        Get current GlitchTip configuration.

        Returns:
            GlitchTip config dictionary (enabled, dsn)
        """
        return self._config.get("glitchtip", {})

    def has_telegram_override(self) -> bool:
        """Check if Telegram config has runtime override."""
        return bool(self._config.get("telegram", {}).get("bot_token"))

    def has_forwarder_override(self) -> bool:
        """Check if Forwarder config has runtime override."""
        return bool(self._config.get("forwarder", {}).get("url"))


# Global runtime config instance
runtime_config = RuntimeConfig()
