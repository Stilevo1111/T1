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
    # Pricing (monthly): Render $7, Neon $0.02/hour
    "render_monthly_cost": 7.0,
    "neon_hourly_cost": 0.02,
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
    total_monthly = (stats['neon_month'] * 0.02) + 7.0 + 1.0
    total_daily = total_monthly / 30
    return (
        f"📈 OpenDota: {stats['opendota_today']:,} / {stats['opendota_limit']:,}\n"
        f"💰 Стоимость: ~0.99$д"
    )


