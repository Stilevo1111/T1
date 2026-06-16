"""
Analytics Dashboard - ресурсы: OpenDota токены, Neon Hours, Render mins
"""
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Данные об использовании (считаем в реальном времени)
_resource_usage = {
    "opendota_tokens": [],  # [(timestamp, tokens_used)]
    "neon_hours": [],       # [(timestamp, hours_used)]
    "render_mins": []      # [(timestamp, mins_used)]
}

def record_opendota_tokens(tokens_used: int):
    """Записать использование токенов OpenDota."""
    _resource_usage["opendota_tokens"].append((time.time(), tokens_used))

def record_neon_hours(hours: float):
    """Записать использование часов Neon."""
    _resource_usage["neon_hours"].append((time.time(), hours))

def record_render_mins(mins: int):
    """Записать использование минут Render."""
    _resource_usage["render_mins"].append((time.time(), mins))

def get_resource_stats(period_hours: int = 24):
    """Получить статистику за период."""
    cutoff = time.time() - period_hours * 3600
    
    def sum_usage(data):
        return sum(amt for ts, amt in data if ts >= cutoff)
    
    return {
        "opendota_tokens_24h": sum_usage(_resource_usage["opendota_tokens"]),
        "neon_hours_24h": sum_usage(_resource_usage["neon_hours"]),
        "render_mins_24h": sum_usage(_resource_usage["render_mins"]),
        "estimated_cost_usd": (
            sum_usage(_resource_usage["neon_hours"]) * 0.02 +  # ~0.02$/час Neon
            sum_usage(_resource_usage["render_mins"]) * 0.0005   # ~$0.0005/мин Render
        )
    }

def generate_dashboard_text():
    """Сгенерировать текст для /about."""
    stats = get_resource_stats(24)
    
    lines = [
        "🤖 <b>Fissure Bot Stats</b>",
        "",
        f"🔤 OpenDota токены (24ч): {stats['opendota_tokens_24h']:,}",
        f"⏱️ Neon Hours (24ч): {stats['neon_hours_24h']:.1f}h",
        f"⚡ Render mins (24ч): {stats['render_mins_24h']:,}",
        f"💰 Стоимость (24ч): ${stats['estimated_cost_usd']:.2f}",
        "",
        "📅 Данные обновляются в реальном времени"
    ]
    return "\n".join(lines)

# Автозапись для существующих функций
_original_get = None

def patch_opendota_tracking():
    """Патчить existing функции для учёта токенов."""
    from dota_mmr import get_dota_data as _get_dota_data
    
    async def patched_get_dota_data(*args, **kwargs):
        result = await _get_dota_data(*args, **kwargs)
        if result:
            record_opendota_tokens(1)  # Примерно 1 запрос = 1 токен
        return result
    
    # Сохранить оригинал для вызова
    global _original_get
    _original_get = _get_dota_data
    return patched_get_dota_data