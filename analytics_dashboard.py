"""
Analytics Dashboard - ресурсы: OpenDota токены, Neon Hours, Render mins
"""
import logging
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_START_TIME = time.time()

_RESOURCE_LIMITS = {
    "opendota_tokens_daily": 3000,
    "neon_hours_monthly": 100,
    "render_hours_monthly": 750,
}

_resource_usage = {
    "opendota_tokens": [],
    "neon_hours": [],
    "render_hours": [],
}

def record_opendota_tokens(tokens_used: int):
    _resource_usage["opendota_tokens"].append((time.time(), tokens_used))

def record_neon_hours(hours: float):
    _resource_usage["neon_hours"].append((time.time(), hours))

def record_render_hours(hours: float):
    _resource_usage["render_hours"].append((time.time(), hours))

def get_resource_stats():
    now = time.time()
    day_ago = now - 24 * 3600
    month_ago = now - 30 * 24 * 3600
    
    opendota_today = sum(t for ts, t in _resource_usage["opendota_tokens"] if ts >= day_ago)
    neon_month = sum(h for ts, h in _resource_usage["neon_hours"] if ts >= month_ago)
    render_month = sum(h for ts, h in _resource_usage["render_hours"] if ts >= month_ago)
    
    render_uptime = int((now - _START_TIME) / 3600) if not render_month else int(render_month)
    
    return {
        "opendota_today": opendota_today,
        "opendota_limit": _RESOURCE_LIMITS["opendota_tokens_daily"],
        "neon_month": neon_month,
        "neon_limit": _RESOURCE_LIMITS["neon_hours_monthly"],
        "render_hours": render_uptime,
        "render_limit": _RESOURCE_LIMITS["render_hours_monthly"],
        "estimated_daily_cost": (
            neon_month * 0.02 / 30 +
            render_uptime * 0.0005 * 24 / 30
        )
    }

def generate_dashboard_text():
    stats = get_resource_stats()
    
    lines = [
        "📈 OpenDota: {opendota_today:,} / {opendota_limit:,}",
        "💾 База данных: {neon_month:.1f} / {neon_limit}",
        "🌐 Сервер: {render_hours} / {render_limit}",
        "💰 Оценочная стоимость: ~${estimated_daily_cost:.2f}д".format(**stats),
    ]
    return "\n".join(lines)


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
        from_time = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        url = ("https://console.neon.tech/api/v2/consumption_history/v2/projects"
               f"?org_id={org_id}&from={from_time}&to={to_time}"
               "&granularity=hourly&metrics=compute_unit_seconds")
        
        headers = {"Authorization": f"Bearer {api_key}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and "data" in data:
                        total_seconds = sum(
                            entry.get("compute_unit_seconds", 0) or 0 
                            for entry in data["data"]
                        )
                        hours = total_seconds / 3600
                        record_neon_hours(hours)
                        return hours
                logger.debug(f"Neon API returned {resp.status}")
                return None
    except Exception as e:
        logger.debug(f"Neon usage fetch failed: {e}")
        return None


async def fetch_render_usage():
    """Fetch actual Render.com usage (requires RENDER_API_KEY)."""
    try:
        import os
        api_key = os.getenv("RENDER_API_KEY")
        service_id = os.getenv("RENDER_SERVICE_ID")
        if not api_key or not service_id:
            return None
        
        import aiohttp
        query = f'{{service(id: "{service_id}") {{metrics {{usedMinutes}}}}}}'
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.render.com/graphql",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"query": query}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and "data" in data:
                        mins = data["data"]["service"]["metrics"]["usedMinutes"] or 0
                        record_render_hours(mins / 60)
                        return mins / 60
                logger.debug(f"Render API returned {resp.status}")
                return None
    except Exception as e:
        logger.debug(f"Render usage fetch failed: {e}")
        return None