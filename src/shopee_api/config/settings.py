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

    # Dashboard Configuration
    dashboard_api_key: Optional[str] = None

    # GlitchTip Error Monitoring
    glitchtip_dsn: Optional[str] = None

    # Redis Queue Configuration
    redis_enabled: bool = True
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_max_retries: int = 3
    redis_num_workers: int = 3
    redis_brpop_timeout: int = 30

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields from .env (e.g., processor-specific vars)


# Create a global settings instance
settings = Settings()
