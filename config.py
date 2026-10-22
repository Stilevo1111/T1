"""Configuration management using Pydantic Settings"""
from __future__ import annotations

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bot configuration with environment variables"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Required
    BOT_TOKEN: str
    DATABASE_URL: str

    # Optional with defaults
    REDIS_URL: str = "redis://localhost:6379"
    ADMIN_CHAT_ID: int | None = None
    OPENAI_API_KEY: str | None = None
    OPENDOTA_API_KEY: str | None = None
    OBS_WIDGET_STEAM_ID: int | None = None

    # Performance settings
    CACHE_TTL: int = 300  # 5 minutes
    DB_POOL_MIN_SIZE: int = 2
    DB_POOL_MAX_SIZE: int = 10
    DB_POOL_TIMEOUT: int = 30

    # Anti-spam (see antispam.py). The limits are applied per action, so a
    # user may freely try every button — repeating the SAME action too soon
    # only gets a friendly "не торопись" instead of a mute.
    SPAM_ACTION_COOLDOWN: float = 4.0    # default cooldown of a single action
    SPAM_NUDGE_COOLDOWN: float = 30.0    # how often the nudge may repeat
    SPAM_SOFT_WINDOW: int = 10           # window of the soft total rate
    SPAM_SOFT_MAX_ACTIONS: int = 20      # actions per window before the nudge
    SPAM_SOFT_COOLDOWN: int = 10         # wait shown when the soft rate is hit

    # Telegram API protection — per chat (see rate_limiter.py)
    TELEGRAM_RATE_LIMIT_PER_SECOND: float = 15.0
    TELEGRAM_RATE_LIMIT_BURST: int = 25

    # Party command settings
    PARTY_MAX_ABOVE: int = 4
    PARTY_MAX_BELOW: int = 3

    # Observability
    PROMETHEUS_ENABLED: bool = False

    @property
    def is_postgresql(self) -> bool:
        return "postgres" in self.DATABASE_URL or "postgresql" in self.DATABASE_URL


# Global settings instance
settings = Settings()
