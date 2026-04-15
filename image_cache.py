import logging
import time
import requests as req
from pathlib import Path

logger = logging.getLogger(__name__)

HERO_ICON_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons"

_cache_dir = Path(__file__).parent / "hero_cache"
_cache_dir.mkdir(exist_ok=True)

_hero_cache = {}


def get_cached_hero_icon(hero_short_name: str, timeout: int = 3) -> bytes | None:
    """Get hero icon from cache or fetch and cache it"""
    current_time = time.time()
    
    if hero_short_name in _hero_cache:
        cached_time, cached_data = _hero_cache[hero_short_name]
        # Бесконечный кеш — герои не меняются
        return cached_data
    
    cache_file = _cache_dir / f"{hero_short_name}.png"
    if cache_file.exists():
        try:
            data = cache_file.read_bytes()
            _hero_cache[hero_short_name] = (current_time, data)
            return data
        except Exception as e:
            logger.debug(f"Error reading cache file {cache_file}: {e}")
    
    try:
        url = f"{HERO_ICON_BASE}/{hero_short_name}.png"
        resp = req.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.content
            try:
                cache_file.write_bytes(data)
            except Exception as e:
                logger.debug(f"Error writing cache file: {e}")
            _hero_cache[hero_short_name] = (current_time, data)
            return data
    except Exception as e:
        logger.debug(f"Error fetching hero icon {hero_short_name}: {e}")
    
    return None


def preload_heroes(heroes_data: dict):
    """Preload hero icons in background"""
    import threading
    
    def _preload():
        for hero_id, hero_info in heroes_data.items():
            try:
                short_name = hero_info.get("short_name", "")
                if short_name:
                    get_cached_hero_icon(short_name)
            except Exception:
                pass
    
    thread = threading.Thread(target=_preload, daemon=True)
    thread.start()
