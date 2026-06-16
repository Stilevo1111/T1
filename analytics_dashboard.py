"""
Analytics Dashboard - ресурсы: OpenDota токены, Neon Hours
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_RESOURCE_LIMITS = {
    "opendota_tokens_daily": 3000,
    "neon_hours_monthly": 100,
    "render_monthly_cost": 7.0,
    "neon_hourly_cost": 0.02,
}

_resource_usage = {
    "opendota_tokens": [],
    "neon_hours": [],
}

_cached_neon_hours = None
_cached_neon_ts = 0
_CACHE_TTL = 300  # 5 minutes

def record_opendota_tokens(tokens_used: int):
    _resource_usage["opendota_tokens"].append((time.time(), tokens_used))

def record_neon_hours(hours: float):
    _resource_usage["neon_hours"].append((time.time(), hours))
    global _cached_neon_hours, _cached_neon_ts
    _cached_neon_hours = hours
    _cached_neon_ts = time.time()

def get_resource_stats():
    now = time.time()
    # Calculate reset time at 03:00 MSK
    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)
    msk_reset = msk_now.replace(hour=3, minute=0, second=0, microsecond=0)
    if msk_now.hour < 3:
        msk_reset = msk_reset - timedelta(days=1)
    reset_ts = msk_reset.timestamp()
    
    opendota_today = sum(t for ts, t in _resource_usage["opendota_tokens"] if ts >= reset_ts)
    month_ago = now - 30 * 24 * 3600
    neon_month = sum(h for ts, h in _resource_usage["neon_hours"] if ts >= month_ago)
    
    return {
        "opendota_today": opendota_today,
        "opendota_limit": _RESOURCE_LIMITS["opendota_tokens_daily"],
        "neon_month": neon_month,
        "neon_limit": _RESOURCE_LIMITS["neon_hours_monthly"],
        "estimated_cost": neon_month * 0.02,
    }

def generate_dashboard_text(neon_hours=None):
    stats = get_resource_stats()
    display_neon = neon_hours if neon_hours is not None else stats['neon_month']
    
    opendota_text = f"📈 OpenDota: {stats['opendota_today']:,} / {stats['opendota_limit']:,} Token"
    
    if neon_hours is None:
        neon_text = f"💾 База данных: 0.0 / {stats['neon_limit']}д"
    else:
        neon_text = f"💾 База данных: {display_neon:.1f} / {stats['neon_limit']}д"
    
    neon_monthly_cost = display_neon * 0.02 if display_neon > 0 else 0.0
    total_monthly = 7.0 + neon_monthly_cost + 1.0
    total_daily = total_monthly / 30
    
    return f"{opendota_text}\n{neon_text}\n💰 Оценочная стоимость: ~${total_daily:.2f}д"


async def fetch_neon_usage(retries=3, delay=2):
    """Fetch actual Neon.tech usage (requires NEON_API_KEY and NEON_ORG_ID)."""
    global _cached_neon_hours, _cached_neon_ts
    
    # Return cached if still valid
    if _cached_neon_hours is not None and time.time() - _cached_neon_ts < _CACHE_TTL:
        return _cached_neon_hours
    
    for attempt in range(retries):
        try:
            import os
            api_key = os.getenv("NEON_API_KEY")
            org_id = os.getenv("NEON_ORG_ID")
            if not api_key or not org_id:
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                    continue
                return None
            
            import aiohttp
            now = datetime.now(timezone.utc)
            from_time = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            to_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            
            url = ("https://console.neon.tech/api/v2/consumption_history/v2/projects"
                   f"?org_id={org_id}&from={from_time}&to={to_time}"
                   "&granularity=hourly&metrics=compute_unit_seconds")
            
            headers = {"Authorization": f"Bearer {api_key}"}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"Neon API response: {data}")
                        if data and "data" in data:
                            total_seconds = sum(
                                entry.get("compute_unit_seconds", 0) or 0 
                                for entry in data["data"]
                            )
                            hours = total_seconds / 3600
                            logger.info(f"Neon compute time: {total_seconds}s = {hours}h")
                            _cached_neon_hours = hours
                            _cached_neon_ts = time.time()
                            record_neon_hours(hours)
                            return hours
                    if attempt < retries - 1:
                        await asyncio.sleep(delay)
        except Exception as e:
            logger.debug(f"Neon usage fetch attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
    return None