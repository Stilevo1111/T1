import asyncio
import logging
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
RATE_LIMIT_COOLDOWN = 60  # 60 seconds cooldown after hitting rate limit


def is_rate_limited():
    """Check if bot is currently rate limited for Telegram API calls."""
    return time.time() < _rate_limit_until


def set_rate_limited(retry_after=None):
    """Set rate limit state. retry_after is seconds to wait (default COOLDOWN)."""
    global _rate_limit_until
    wait_time = retry_after if retry_after else RATE_LIMIT_COOLDOWN
    _rate_limit_until = time.time() + wait_time
    logger.warning(f"Rate limited until {time.strftime('%H:%M:%S', time.localtime(_rate_limit_until))}")


class RateLimiter:
    """
    Token bucket rate limiter for Telegram API calls.
    Allows bursts up to bucket_size, then refills at rate tokens_per_second.
    """

    def __init__(self, tokens_per_second: float = 20.0, bucket_size: int = 40):
        """
        Initialize rate limiter.
        
        Args:
            tokens_per_second: Rate at which tokens are added (default 20/sec)
            bucket_size: Maximum burst size (default 40 tokens)
        """
        self.tokens_per_second = tokens_per_second
        self.bucket_size = bucket_size
        self.tokens = float(bucket_size)  # Start with full bucket
        self.last_update = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Acquire tokens from the bucket. Waits if necessary.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            True if tokens were acquired
        """
        async with self._lock:
            now = time.time()
            # Add tokens based on time passed
            time_passed = now - self.last_update
            self.tokens = min(
                self.bucket_size,
                self.tokens + time_passed * self.tokens_per_second
            )
            self.last_update = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            else:
                # Not enough tokens, calculate wait time
                needed = tokens - self.tokens
                wait_time = needed / self.tokens_per_second
                logger.debug(f"Rate limiter: waiting {wait_time:.2f}s for {tokens} tokens")
                await asyncio.sleep(wait_time)
                # Retry after waiting
                return await self.acquire(tokens)

    def try_acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens without waiting.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            True if tokens were acquired, False otherwise
        """
        now = time.time()
        # Add tokens based on time passed
        time_passed = now - self.last_update
        self.tokens = min(
            self.bucket_size,
            self.tokens + time_passed * self.tokens_per_second
        )
        self.last_update = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def get_available_tokens(self) -> float:
        """Get current number of available tokens."""
        now = time.time()
        time_passed = now - self.last_update
        tokens = min(
            self.bucket_size,
            self.tokens + time_passed * self.tokens_per_second
        )
        return tokens

# Global rate limiter instance for the bot
# Telegram allows up to 30 messages per second, but we'll be conservative
telegram_rate_limiter = RateLimiter(tokens_per_second=15.0, bucket_size=30)

def rate_limit(tokens: int = 1):
    """
    Decorator to apply rate limiting to async functions.
    
    Usage:
        @rate_limit(tokens=1)
        async def send_message(...):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            await telegram_rate_limiter.acquire(tokens)
            return await func(*args, **kwargs)
        return wrapper
    return decorator
