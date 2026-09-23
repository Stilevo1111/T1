"""
Analytics Dashboard - ресурсы: OpenDota токены, Neon Hours
"""
import json
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

def load_resource_stats():
    """Загружает статистику из БД при старте (чтобы не терять при деплое)."""
    from database import get_config
    now = time.time()
    
    # Загружаем OpenDota токены за последние 2 дня (чтобы покрыть смену даты)
    opendota_data = get_config('analytics_opendota_tokens')
    if opendota_data:
        try:
            stored = json.loads(opendota_data)
            # Фильтруем записи за последние 2 дня
            two_days_ago = now - 2 * 24 * 3600
            _resource_usage["opendota_tokens"] = [(ts, t) for ts, t in stored if ts >= two_days_ago]
            logger.info(f"analytics: loaded {len(_resource_usage['opendota_tokens'])} opendota token records")
        except Exception as e:
            logger.warning(f"analytics: failed to load opendota stats: {e}")
    
    # Загружаем Neon часы за последний месяц
    neon_data = get_config('analytics_neon_hours')
    if neon_data:
        try:
            stored = json.loads(neon_data)
            month_ago = now - 30 * 24 * 3600
            _resource_usage["neon_hours"] = [(ts, h) for ts, h in stored if ts >= month_ago]
            logger.info(f"analytics: loaded {len(_resource_usage['neon_hours'])} neon hour records")
        except Exception as e:
            logger.warning(f"analytics: failed to load neon stats: {e}")

def save_resource_stats():
    """Сохраняет текущую статистику в БД."""
    from database import set_config
    try:
        if _resource_usage["opendota_tokens"]:
            set_config('analytics_opendota_tokens', json.dumps(_resource_usage["opendota_tokens"]))
        if _resource_usage["neon_hours"]:
            set_config('analytics_neon_hours', json.dumps(_resource_usage["neon_hours"]))
    except Exception as e:
        logger.warning(f"analytics: failed to save stats: {e}")

def record_opendota_tokens(tokens_used: int):
    _resource_usage["opendota_tokens"].append((time.time(), tokens_used))
    save_resource_stats()

def record_neon_hours(hours: float):
    _resource_usage["neon_hours"].append((time.time(), hours))
    save_resource_stats()

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


