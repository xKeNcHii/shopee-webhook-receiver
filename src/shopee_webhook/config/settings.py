"""Configuration management using Pydantic Settings.

Loads configuration from environment variables with .env file support.
"""

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration."""

    # Shopee API Configuration
    partner_id: Optional[int] = None
    partner_key: Optional[str] = None
    shop_id: Optional[int] = None
    access_token: Optional[str] = None
    webhook_partner_key: Optional[str] = None
    refresh_token: Optional[str] = None

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    environment: str = "development"

    # Telegram Configuration
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # API Configuration
    host_api: str = "https://partner.shopeemobile.com"

    # Forwarding Configuration
    forward_webhook_url: Optional[str] = None

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False


# Create a global settings instance
settings = Settings()
