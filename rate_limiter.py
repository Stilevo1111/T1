import functools
import logging
import threading
import time

logger = logging.getLogger(__name__)

__all__ = [
    "RateLimiter",
    "KeyedRateLimiter",
    "telegram_rate_limiter",
    "chat_rate_limiter",
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


# Account-wide Telegram API budget. Telegram allows roughly 30 messages per
# second for a bot, so this stays below that limit. It is the outermost
# layer only — the per-user anti-spam lives in antispam.py.
telegram_rate_limiter = RateLimiter(tokens_per_second=25.0, bucket_size=50)


class KeyedRateLimiter:
    """
    A pool of token buckets — one per key (usually one per chat).

    A single global bucket means that one noisy chat eats the budget of every
    other chat, while the noisy chat itself is barely affected. Keying the
    buckets by chat isolates them from each other.
    """

    def __init__(self, tokens_per_second: float = 15.0, bucket_size: int = 25, max_keys: int = 500):
        self.tokens_per_second = tokens_per_second
        self.bucket_size = bucket_size
        self.max_keys = max_keys
        self._buckets: dict[str, RateLimiter] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def _bucket(self, key: str) -> RateLimiter:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = RateLimiter(self.tokens_per_second, self.bucket_size)
            self._buckets[key] = bucket
            self._order.append(key)
            while len(self._order) > self.max_keys:
                self._buckets.pop(self._order.pop(0), None)
        return bucket

    async def acquire(self, key: str, tokens: int = 1) -> bool:
        with self._lock:
            return self._bucket(key).try_acquire(tokens)

    def try_acquire(self, key: str, tokens: int = 1) -> bool:
        with self._lock:
            return self._bucket(key).try_acquire(tokens)

    def get_available_tokens(self, key: str) -> float:
        with self._lock:
            return self._bucket(key).get_available_tokens()

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._buckets.clear()
                self._order.clear()
                return
            self._buckets.pop(key, None)
            if key in self._order:
                self._order.remove(key)


def _chat_key(args, kwargs) -> str:
    """Best-effort extraction of a chat id from a handler call."""
    candidates = [kwargs.get("update"), kwargs.get("context")]
    candidates.extend(args)
    for candidate in candidates:
        if candidate is None:
            continue
        chat = getattr(candidate, "effective_chat", None)
        if chat is not None:
            return f"chat:{chat.id}"
    return "global"


def _load_chat_limits() -> tuple[float, int]:
    try:
        from config import settings
    except Exception:
        return 15.0, 25
    return (
        float(getattr(settings, "TELEGRAM_RATE_LIMIT_PER_SECOND", 15.0)),
        int(getattr(settings, "TELEGRAM_RATE_LIMIT_BURST", 25)),
    )


_chat_rate, _chat_burst = _load_chat_limits()

# Per-chat Telegram API protection. A single chat can no longer monopolise
# the whole bot output budget, and the burst is small enough that a chat
# never receives a wall of bot messages.
chat_rate_limiter = KeyedRateLimiter(
    tokens_per_second=_chat_rate, bucket_size=_chat_burst
)


def rate_limit(tokens: int = 1):
    """
    Decorator to apply rate limiting to async functions.

    Two layers are used: the account-wide Telegram API budget and a per-chat
    budget, so a flood in one chat does not silence the bot everywhere else.
    This is only the API safety net — the per-user anti-spam that actually
    stops a spammer lives in antispam.py.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            key = _chat_key(args, kwargs)
            if not await telegram_rate_limiter.acquire(tokens):
                logger.warning(f"Rate limited: {func.__name__} (account budget)")
                return
            if not await chat_rate_limiter.acquire(key, tokens):
                logger.warning(f"Rate limited: {func.__name__} (bucket={key})")
                return
            return await func(*args, **kwargs)
        return wrapper
    return decorator

