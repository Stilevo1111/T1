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
    
    render_uptime = render_month if render_month > 0 else (now - _START_TIME) / 3600
    
    return {
        "opendota_today": opendota_today,
        "opendota_limit": _RESOURCE_LIMITS["opendota_tokens_daily"],
        "neon_month": neon_month,
        "neon_limit": _RESOURCE_LIMITS["neon_hours_monthly"],
        "render_hours": int(render_uptime),
        "render_limit": _RESOURCE_LIMITS["render_hours_monthly"],
        "estimated_daily_cost": (
            neon_month * 0.02 / 30 +
            render_uptime * 0.0005 * 24 / 30
        )
    }

def generate_dashboard_text():
    stats = get_resource_stats()
    return (
        f"📈 OpenDota: {stats['opendota_today']:,} / {stats['opendota_limit']:,}\n"
        f"💾 База данных: {stats['neon_month']:.1f} / {stats['neon_limit']}\n"
        f"🌐 Сервер: {stats['render_hours']} / {stats['render_limit']}\n"
        f"💰 Оценочная стоимость: ~${stats['estimated_daily_cost']:.2f}д"
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


async def fetch_render_usage():
    """Fetch actual Render.com usage (requires RENDER_API_KEY)."""
    try:
        import os
        from datetime import datetime
        api_key = os.getenv("RENDER_API_KEY")
        service_id = os.getenv("RENDER_SERVICE_ID", "srv-d5rhtsh4tr6s73e39k20")
        if not api_key:
            return None
        
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.render.com/v1/services/{service_id}/deploys",
                headers={"Authorization": f"Bearer {api_key}"}
            ) as resp:
                if resp.status == 200:
                    deploys = await resp.json()
                    last_live = None
                    for item in deploys:
                        deploy = item.get("deploy", {})
                        if deploy.get("status") == "live":
                            started = deploy.get("startedAt")
                            if started:
                                last_live = datetime.fromisoformat(started.replace("Z", "+00:00"))
                                break
                    
                    if last_live:
                        now = datetime.now(timezone.utc)
                        uptime_hours = (now - last_live).total_seconds() / 3600
                        record_render_hours(uptime_hours)
                        logger.info(f"Render uptime: {uptime_hours:.1f}h from live deploy")
                    else:
                        uptime_hours = (time.time() - _START_TIME) / 3600
                        record_render_hours(uptime_hours)
                        logger.info(f"Render uptime: {uptime_hours:.1f}h (fallback to bot runtime)")
                    return uptime_hours
                logger.debug(f"Render API returned {resp.status}")
                return None
    except Exception as e:
        logger.debug(f"Render usage fetch failed: {e}")
        return None
        
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # Get last live deploy to calculate current uptime
            async with session.get(
                f"https://api.render.com/v1/services/{service_id}/deploys",
                headers={"Authorization": f"Bearer {api_key}"}
            ) as resp:
                if resp.status == 200:
                    deploys = await resp.json()
                    last_live = None
                    for item in deploys:
                        deploy = item.get("deploy", {})
                        if deploy.get("status") == "live":
                            started = deploy.get("startedAt")
                            if started:
                                last_live = datetime.fromisoformat(started.replace("Z", "+00:00"))
                                break
                    
                    if last_live:
                        now = datetime.now(timezone.utc)
                        uptime_hours = (now - last_live).total_seconds() / 3600
                        record_render_hours(uptime_hours)
                        logger.info(f"Render uptime calculated: {uptime_hours:.1f}h from deploy {deploy.get('id', 'unknown')}")
                        return uptime_hours
                logger.debug(f"Render API returned {resp.status}")
                return None
    except Exception as e:
        logger.debug(f"Render usage fetch failed: {e}")
        return None