"""Кеш иконок героев на диске (hero_cache/)."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent / "hero_cache"
_MEMORY_CACHE: dict[str, bytes] = {}


def get_cached_hero_icon(hero_short_name: str) -> bytes | None:
    if not hero_short_name:
        return None
    key = hero_short_name.lower()
    if key in _MEMORY_CACHE:
        return _MEMORY_CACHE[key]
    path = _CACHE_DIR / f"{key}.png"
    if path.exists():
        try:
            data = path.read_bytes()
            _MEMORY_CACHE[key] = data
            return data
        except OSError as e:
            logger.debug(f"hero icon read failed {key}: {e}")
    return None


def preload_heroes(heroes_data) -> None:
    """Прогрев: создаём каталог кеша; иконки подгружаются по запросу."""
    try:
        _CACHE_DIR.mkdir(exist_ok=True)
        count = len(heroes_data) if heroes_data else 0
        logger.info(f"image_cache: ready ({count} heroes in manifest)")
    except OSError as e:
        logger.warning(f"image_cache preload: {e}")
