"""
Analytics Dashboard - ресурсы: OpenDota токены, Neon Hours
"""
import logging
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_RESOURCE_LIMITS = {
    "opendota_tokens_daily": 3000,
    "neon_hours_monthly": 100,
}

_resource_usage = {
    "opendota_tokens": [],
    "neon_hours": [],
}

def record_opendota_tokens(tokens_used: int):
    _resource_usage["opendota_tokens"].append((time.time(), tokens_used))

def record_neon_hours(hours: float):
    _resource_usage["neon_hours"].append((time.time(), hours))

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

def generate_dashboard_text():
    stats = get_resource_stats()
    return (
        f"📈 OpenDota: {stats['opendota_today']:,} / {stats['opendota_limit']:,}\n"
        f"💾 База данных: {stats['neon_month']:.1f} / {stats['neon_limit']}ч\n"
        f"💰 Стоимость: ~${stats['estimated_cost']:.2f}"
    )


async def fetch_neon_usage():
    """Fetch actual Neon.tech usage (requires NEON_API_KEY and NEON_ORG_ID)."""
    try:
        import os
        api_key = os.getenv("NEON_API_KEY")
        org_id = os.getenv("NEON_ORG_ID")
        if not api_key or not org_id:
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
                        record_neon_hours(hours)
                        return hours
                logger.debug(f"Neon API returned {resp.status}")
                return None
    except Exception as e:
        logger.debug(f"Neon usage fetch failed: {e}")
        return None