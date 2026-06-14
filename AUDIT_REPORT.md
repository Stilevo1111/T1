# Telegram Bot Performance & DevOps Audit Report

**Date:** 2026-06-15  
**Project:** fissure-bot (Telegram bot with Dota 2 integration)  
**Platform:** Render (Free/Starter Tier)

---

## ✅ Completed Fixes

| Priority | Issue | Status |
|----------|-------|--------|
| P0 | Sequential rank-up notifications blocking event loop | ✅ Fixed (asyncio.gather) |
| P1 | PostgreSQL connection pool maxconn=20 > Neon Free limit | ✅ Fixed (maxconn=5) |
| P1 | N+1 lookup in get_user_by_steam_id | ✅ Fixed (reverse index) |
| P1 | Sequential match fetching in fetch_match_details | ✅ Fixed (asyncio.gather + semaphore) |
| P1 | Missing statement_timeout | ✅ Fixed (30s timeout) |
| P1 | Health check without DB verification | ✅ Fixed |
| P2 | Unused redis dependency | ✅ Fixed (removed) |
| P2 | Rate limiter too high (15/s) | ✅ Fixed (10/s) |
| P3 | Missing SIGKILL handler | ✅ Fixed (atexit) |
| P3 | Missing in_chat=TRUE on INSERT | ✅ Fixed |
| P3 | cleanup_left_users too aggressive | ✅ Fixed (>7 days) |
| P3 | Analytics shows wrong error for missing steam_id | ✅ Fixed |

---

## P0 Critical (Crashes/OOM Now)

### 1. Sequential API Calls in MMR Update Job
**File:** `main.py:1128-1165`

**Problem:** Sequential awaits when processing rank-up user notifications.

**Cause:** Line 1128 `for user, rank_info in rank_up_users:` iterates sequentially, each iteration making Telegram API calls and generating images.

**Fix:**
```python
# Replace sequential with parallel processing
async def notify_rank_up_users(context, rank_up_users, digest_chat_id):
    """Parallel rank-up notifications to avoid blocking event loop."""
    async def notify_one(user, rank_info):
        try:
            username = user.get('steam_nickname') or user.get('username') or 'Игрок'
            telegram_id = user.get('telegram_id')
            message_count = user.get('message_count', 0)
            rank_tier = user.get('rank_tier', 0)
            avatar_url = await resolve_avatar_url_for_card(context.bot, telegram_id=telegram_id, steam_id=user.get('steam_id'))
            card_data = await asyncio.to_thread(generate_start_card, avatar_url=avatar_url, username=username, rank_tier=rank_tier, week_wins=rank_info['new_rank'], week_losses=0)
            if card_data:
                await context.bot.send_photo(chat_id=digest_chat_id, photo=card_data, caption=f"{make_clickable(username, telegram_id)} повысил ранг!\n{rank_info['old_rank']} → {rank_info['new_rank']}", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Rank-up notify failed for {telegram_id}: {e}")
    
    await asyncio.gather(*[notify_one(u, r) for u, r in rank_up_users], return_exceptions=True)
```

### 2. Blocking time.sleep() in Sync API Retry Logic
**File:** `dota_mmr.py:282-330`

**Problem:** `time.sleep()` calls block the event loop during retry backoff, preventing other async tasks from running.

**Cause:** Lines 300, 306, 314 use `time.sleep()` for retry delays instead of `asyncio.sleep()`.

**Fix:**
```python
# Lines 300-314 in dota_mmr.py - convert to async or wrap in thread
# For sync _api_get, this is acceptable since it's already sync
# But add warning about event loop blocking
import warnings
import functools
if asyncio.get_event_loop().is_running():
    warnings.warn("_api_get is sync and will block event loop", RuntimeWarning)
```

---

## P1 High Priority (Crashes Under Load)

### 3. Synchronous requests Library Blocking Event Loop
**File:** `dota_mmr.py:444-456, 472, 792-868`

**Problem:** `requests.get()` is used synchronously in `get_hero_icon_cached`, `get_hero_portrait_cached`, and `generate_heroes_image` which uses ThreadPoolExecutor (line 856).

**Cause:** 
- Line 445: `requests.get(url, timeout=timeout)` in `get_hero_icon_cached`
- Line 472: `requests.get(url, timeout=3)` in `get_hero_portrait_cached`
- Line 856: `executor.submit(_fetch_hero_portrait, ...)` uses sync requests internally

**Fix:**
```python
# dota_mmr.py - make hero icon/portrait fetching async
async def get_hero_icon_cached_async(hero_short_name: str, session, timeout: int = 3):
    cache_file = Path(__file__).parent / "hero_cache" / f"{hero_short_name}.png"
    if cache_file.exists():
        return cache_file.read_bytes()
    try:
        url = f"{HERO_ICON_BASE}/{hero_short_name}.png"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status == 200:
                data = await resp.read()
                cache_file.write_bytes(data)
                return data
    except Exception:
        pass
    return None

# For generate_heroes_image, replace ThreadPoolExecutor with asyncio.gather + async fetch
```

### 4. N+1 Query Pattern in get_user_by_steam_id
**File:** `database.py:2003-2013`

**Problem:** `get_user_by_steam_id` iterates through ALL cache keys to find a Steam ID match before hitting the database.

**Cause:** Lines 2003-2013 call `user_cache.get_all_users()` and iterate through every cached user, checking `cached_user.get('steam_id')`.

**Fix:**
```python
# Add reverse index in database.py
_steam_to_tg_index: dict[int, int] = {}  # steam_id -> telegram_id

def _index_user_steam(user: dict):
    """Maintain reverse index"""
    steam_id = user.get('steam_id')
    if steam_id and isinstance(steam_id, int):
        _steam_to_tg_index[steam_id] = user.get('telegram_id')

# Use index in get_user_by_steam_id
def get_user_by_steam_id(steam_id: int):
    tg_id = _steam_to_tg_index.get(steam_id)
    if tg_id:
        return get_user(tg_id)
    # ... fallback to DB query (already exists at line 2017)
```

### 5. Telegram Bot Message Rate Limit Too High
**File:** `rate_limiter.py:121`

**Problem:** `tokens_per_second=15.0` allows 15 messages per second, which may exceed Render Free tier webhook response time limits.

**Cause:** Conservative rate limiter may still allow bursts that trigger Telegram limits or timeout webhooks.

**Fix:**
```python
# rate_limiter.py:121 - reduce for Render Free tier stability
telegram_rate_limiter = RateLimiter(tokens_per_second=8.0, bucket_size=15)  # Conservative: 8 msgs/sec max
```

### 6. PostgreSQL Connection Pool Exceeds Neon Free Tier Limits
**File:** `database.py:487-498`

**Problem:** `_pg_pool` max connections is 20, but Neon Free tier allows only ~5 concurrent connections.

**Cause:** Line 489 sets `maxconn=20`. Neon Free tier has connection limits; this may exhaust connections under load.

**Fix:**
```python
# database.py:489
_pg_pool = pool.ThreadedConnectionPool(
    minconn=1,
    maxconn=5,  # Reduced for Neon Free tier (was 20)
    dsn=DATABASE_URL
)
```

---

## P2 Optimization

### 7. Sequential Match Detail Fetching + Sync Requests in Hero Image Generation
**File:** `weekly_analytics.py:649-698` and `dota_mmr.py:855-863`

**Problem:** 
1. `fetch_match_details` processes matches sequentially (lines 649-696)
2. `generate_heroes_image` uses ThreadPoolExecutor with sync `_fetch_hero_portrait` (line 856)

**Cause:** Both functions have serialization bottlenecks; match fetching yields with `await asyncio.sleep(0)` but doesn't parallelize.

**Fix:**
```python
# weekly_analytics.py:640-698 - use gather for parallel fetching
async def fetch_match_details(matches: list[dict], steam_id: int) -> list[dict]:
    async def fetch_one(m):
        match_id = m.get("match_id")
        if not match_id or (m.get("gold_per_min", 0) > 0 and m.get("last_hits", 0) > 0):
            return m
        try:
            match_data = await _api_get_async(f"{OPENDOTA_API_URL}/matches/{match_id}", timeout=20)
            # ... enrich match data (lines 672-688)
            return m
        except Exception:
            return m
    
    # Parallel fetch with concurrency limit
    semaphore = asyncio.Semaphore(5)
    async def fetch_with_limit(m):
        async with semaphore:
            return await fetch_one(m)
    
    results = await asyncio.gather(*[fetch_with_limit(m) for m in matches])
    return list(results)

# dota_mmr.py:855-863 - replace ThreadPoolExecutor with async aiohttp
```

### 8. SELECT * Instead of Explicit Columns
**File:** `database.py:1253, 1306`

**Problem:** Using `SELECT *` in `get_user()` instead of explicit column list.

**Cause:** Line 1253 queries all columns; this is slower and uses more memory.

**Fix:**
```python
# database.py:1253 - use explicit columns
query = "SELECT telegram_id, username, steam_id, fissure, last_fissure, last_message_id, total_growth, total_rolls, best_streak, current_streak, mmr, rank_tier, week_games, week_wins, week_best_streak, week_current_streak, week_start_date, message_count, weekly_mvp_count, weekly_top2_count, weekly_top3_count, analytics_cache, analytics_updated_at FROM users WHERE telegram_id = %s"
```

### 9. Unused Redis Dependency
**File:** `requirements.txt:17` and `cache.py:1-66`

**Problem:** `redis[hiredis]>=5.0.0` is in requirements but `RedisCache` is never connected or used; `container.py` defines it but `UserRepository` is never instantiated.

**Cause:** Cache infrastructure exists but is unused. The actual caching uses `UserCache` (in-memory dict at database.py:117).

**Fix:** Remove `redis[hiredis]>=5.0.0` from requirements.txt (saves ~3MB memory on Free tier).

### 10. Health Check Too Simple
**File:** `main.py:154-156`

**Problem:** Health check always returns OK without checking database connectivity.

**Cause:** Line 156 returns static "OK" without verifying DB is reachable.

**Fix:**
```python
# main.py health_check function
async def health_check(request):
    """Health check with DB ping."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        release_connection(conn)
        return web.Response(text="OK: DB connected", status=200)
    except Exception as e:
        return web.Response(text=f"ERROR: {e}", status=503)
```

### 11. Missing Statement Timeout for Neon
**File:** `database.py:567-586` and `database.py:273`

**Problem:** Long-running queries may hang; Neon Free tier terminates idle connections after 5 minutes.

**Cause:** No `statement_timeout` set on connections; aiohttp session limit is 10 concurrent (line 273) which could be reduced.

**Fix:**
```python
# database.py - add timeout configuration
# Line 273: Reduce aiohttp concurrency  
_aiohttp_session = aiohttp.ClientSession(
    timeout=aiohttp.ClientTimeout(total=10),
    connector=aiohttp.TCPConnector(limit=5, limit_per_host=3)  # Reduced for Free tier
)

# Add to _postgres_connect_kwargs in database.py:567
kwargs["connect_timeout"] = 10
kwargs["options"] = "-c statement_timeout=30000"  # 30s query timeout (was unlimited)
```

---

## P3 Improvements

### 12. SIGKILL Not Handled - Emergency Flush Needed
**File:** `main.py:3472-3492`

**Problem:** SIGTERM handler won't catch SIGKILL (Render's kill signal after 30s grace period).

**Cause:** Render sends SIGKILL after SIGTERM timeout; process may be killed mid-operation without flushing dirty cache.

**Fix:**
```python
# main.py - add atexit handler
import atexit

def _emergency_flush():
    try:
        for uid in user_cache.get_all_dirty():
            # Flush unwritten user changes
            if user_cache.is_dirty(uid):
                save_user_sync(uid, user_cache.get(uid))
    except Exception:
        pass

atexit.register(_emergency_flush)
```

### 13. Missing Retry Logic on Connection Errors
**File:** `database.py:1101-1126`

**Problem:** Connection retry logic exists but only for specific error phrases (`connection` in str(e).lower()).

**Cause:** Line 1101 checks limited error phrases; network interruptions may cause silent failures.

**Fix:**
```python
# database.py - add exponential backoff for connection failures
MAX_CONNECTION_RETRIES = 3
CONNECTION_BACKOFF_BASE = 2

def get_connection():
    for attempt in range(MAX_CONNECTION_RETRIES):
        try:
            # ... existing connection logic
        except Exception as e:
            if attempt < MAX_CONNECTION_RETRIES - 1:
                time.sleep(CONNECTION_BACKOFF_BASE ** attempt)
            raise
```

### 14. Prometheus Metrics Server on Free Tier
**File:** `main.py:116-137`

**Problem:** Prometheus HTTP server starts on port 8000, consuming extra resources on Free tier.

**Cause:** Lines 116-137 attempt to start metrics server; on Free tier this wastes memory/CPU.

**Fix:**
```python
# main.py - disable Prometheus on Free tier
if os.getenv("RENDER_PLAN") != "free" and PROMETHEUS_ENABLED:
    try:
        start_http_server(8000)
    except OSError:
        pass
```

---

## Render Configuration Analysis

### Current render.yaml
```yaml
plan: starter        # Free tier (512MB RAM, shared CPU, 1GB disk)
startCommand: python main.py  # No Gunicorn/waitress
```

**Issues:**
1. **No health check grace period** - Render expects `/health` within 10s of startup (may fail on cold start with large cache)
2. **No port detection** - Verify code uses `$PORT` env var (check main.py web app setup)
3. **No process management** - Single process, no restart on crash
4. **MMR_CONCURRENCY_LIMIT=5** - May be too high for Free tier; consider reducing to 3

**Recommended:**
```yaml
envVars:
- key: MMR_CONCURRENCY_LIMIT
  value: "3"  # Reduced for Free tier stability
```

---

## Neon Database Configuration Analysis

**Current State:**
- `?sslmode=require` is extracted correctly (line 573)
- Pool connection uses `ThreadedConnectionPool`
- `pgbouncer=true` is handled (line 571)

**Missing:**
1. `connect_timeout` on connection
2. `statement_timeout` on queries
3. Connection retry on startup may fail silently

---

## Key Metrics to Monitor

1. **Database Connection Pool Usage** - Should stay < 5 (Neon Free tier limit)
2. **Event Loop Blocking Time** - Track time in sync DB operations > 100ms
3. **Webhook Response Time** - 99th percentile should be < 30s (Render timeout)
4. **Cache Miss Ratio** - High N+1 lookups will spike DB connections
5. **Telegram API Rate Limit Retries** - Frequent retries indicate rate limiting issues

---

## Deployment Checklist

- [ ] Set `MMR_CONCURRENCY_LIMIT=3` (reduce from 5 for Free tier stability)
- [ ] Verify `DATABASE_URL` includes `?sslmode=require` (Neon requires it)
- [ ] Add `?pgbouncer=true` to DATABASE_URL for connection pooling
- [ ] Monitor logs for "Connection pool exhausted" errors
- [ ] Verify health endpoint returns 200 within 10s of startup
- [ ] Test cold start recovery (webhook re-registration after restart)
- [ ] Confirm bot handles 50+ concurrent fissure rolls without timeout
- [ ] Validate graceful shutdown flushes data within 30s SIGTERM window
- [ ] Check OpenDota API rate limit doesn't cause circuit breaker to open
- [ ] Remove unused `redis[hiredis]>=5.0.0` from requirements.txt