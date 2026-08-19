import logging
import threading
import time

logger = logging.getLogger(__name__)

__all__ = [
    "RateLimiter",
    "telegram_rate_limiter",
    "rate_limit",
    "is_rate_limited",
    "set_rate_limited",
]

# Global state for Telegram API rate limit protection
_rate_limit_until = 0
RATE_LIMIT_COOLDOWN = 60


def is_rate_limited():
    """Check if bot is currently rate limited for Telegram API calls."""
    return time.monotonic() < _rate_limit_until


def set_rate_limited(retry_after=None):
    """Set rate limit state. retry_after is seconds to wait (default COOLDOWN)."""
    global _rate_limit_until
    wait_time = retry_after if retry_after else RATE_LIMIT_COOLDOWN
    _rate_limit_until = time.monotonic() + wait_time
    logger.warning(f"Rate limited for {wait_time}s")


class RateLimiter:
    """
    Thread-safe token bucket rate limiter.
    Allows bursts up to bucket_size, then refills at rate tokens_per_second.
    """

    def __init__(self, tokens_per_second: float = 20.0, bucket_size: int = 40):
        self.tokens_per_second = tokens_per_second
        self.bucket_size = bucket_size
        self.tokens = float(bucket_size)
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        time_passed = now - self.last_update
        self.tokens = min(
            self.bucket_size,
            self.tokens + time_passed * self.tokens_per_second
        )
        self.last_update = now

    async def acquire(self, tokens: int = 1) -> bool:
        """Acquire tokens from the bucket. Never blocks; returns False if not enough tokens."""
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def try_acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens without waiting."""
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def get_available_tokens(self) -> float:
        """Get current number of available tokens."""
        with self._lock:
            self._refill()
            return self.tokens


telegram_rate_limiter = RateLimiter(tokens_per_second=10.0, bucket_size=20)


def rate_limit(tokens: int = 1):
    """
    Decorator to apply rate limiting to async functions.
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            if not await telegram_rate_limiter.acquire(tokens):
                logger.debug(f"Rate limited: {func.__name__}")
                return
            return await func(*args, **kwargs)
        return wrapper
    return decorator

