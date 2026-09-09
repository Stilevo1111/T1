"""Tests for local asset loading in this bot version."""
from pathlib import Path

import pytest

from constants import (
    BANNER_DIR,
    TOPMMR_BANNER_PATH,
    get_banner_path,
    get_random_cooldown_banner_path,
)


class TestBannerPaths:
    """Local banner files exist and paths are correct."""

    def test_topmmr_banner_exists(self):
        assert Path(TOPMMR_BANNER_PATH).exists()

    def test_topmmr_banner_is_webp(self):
        assert TOPMMR_BANNER_PATH.endswith(".webp")

    def test_get_banner_path_returns_webp(self):
        for name in ("cooldown", "cooldown_2", "topmmr", "heroes_profil"):
            path = get_banner_path(name)
            assert str(path).endswith(".webp")

    def test_banner_directory_exists(self):
        assert BANNER_DIR.exists()
        assert BANNER_DIR.is_dir()


class TestRandomCooldownBanner:
    """Random cooldown banner picks from known list."""

    def test_returns_existing_banner(self):
        for _ in range(20):
            path = get_random_cooldown_banner_path()
            assert path.exists()
            assert path.suffix == ".webp"


class TestHeroAssets:
    """Hero icons and portraits are available locally."""

    @pytest.fixture(scope="class")
    def heroes(self):
        from dota_mmr import get_heroes_data

        return get_heroes_data()

    def test_heroes_data_loaded(self, heroes):
        assert len(heroes) > 0

    def test_all_hero_image_urls_exist(self, heroes):
        missing = []
        for hero_id, hero in heroes.items():
            img = Path(hero.get("image_url", ""))
            if not img.exists():
                missing.append((hero_id, hero.get("name"), str(img)))
        assert not missing, f"Missing hero portraits: {missing[:5]}"

    def test_all_hero_icon_urls_exist(self, heroes):
        missing = []
        for hero_id, hero in heroes.items():
            icon = Path(hero.get("icon_url", ""))
            if not icon.exists():
                missing.append((hero_id, hero.get("name"), str(icon)))
        assert not missing, f"Missing hero icons: {missing[:5]}"

    def test_hero_paths_are_webp(self, heroes):
        for hero_id, hero in heroes.items():
            assert hero["image_url"].endswith(".webp")
            assert hero["icon_url"].endswith(".webp")
            assert hero["img"].endswith(".webp")


class TestHeroIconCache:
    """Local hero icon cache functions return bytes for known heroes."""

    @pytest.mark.parametrize("hero_name", ["antimage", "axe", "bane", "zuus", "doom", "magnus"])
    def test_get_hero_icon_cached(self, hero_name):
        from dota_mmr import get_hero_icon_cached

        data = get_hero_icon_cached(hero_name)
        assert data is not None
        assert isinstance(data, bytes)
        assert len(data) > 0

    @pytest.mark.parametrize("hero_name", ["antimage", "axe", "bane", "zuus", "doom", "magnus"])
    def test_get_hero_portrait_cached(self, hero_name):
        from dota_mmr import get_hero_portrait_cached

        data = get_hero_portrait_cached(hero_name)
        assert data is not None
        assert isinstance(data, bytes)
        assert len(data) > 0


class TestCachedHeroPortraitAsync:
    """Async hero portrait loader returns PIL images."""

    @pytest.mark.parametrize("hero_name", ["antimage", "axe", "bane", "zuus", "doom", "magnus"])
    def test_get_cached_hero_portrait(self, hero_name):
        import asyncio

        from dota_mmr import get_cached_hero_portrait

        img = asyncio.run(get_cached_hero_portrait(hero_name))
        assert img is not None
        assert img.mode == "RGBA"


class TestFetchHeroIconLocal:
    """hero_meta.fetch_hero_icon resolves from local assets."""

    @pytest.mark.parametrize(
        "icon_path,desc",
        [
            ("antimage", "cdn_name"),
            ("/apps/dota2/images/dota/heroes/antimage_sb.png", "old_format"),
            ("axe", "cdn_name_2"),
        ],
    )
    def test_fetch_hero_icon_local(self, icon_path, desc):
        import asyncio

        from hero_meta import fetch_hero_icon

        img = asyncio.run(fetch_hero_icon(None, icon_path))
        assert img is not None, f"failed for {desc}"
        assert img.mode == "RGBA"


class TestWeeklyAnalyticsHeroIcon:
    """weekly_analytics._get_hero_icon loads from local cache."""

    @pytest.mark.parametrize("hero_id", [1, 2, 3, 113, 114])
    def test_get_hero_icon_local(self, hero_id):
        import asyncio

        from weekly_analytics import _get_hero_icon

        img = asyncio.run(_get_hero_icon(hero_id))
        assert img is not None
        assert img.mode == "RGBA"


class TestObsWidgetLocalPath:
    """obs_widget._fetch_hero_icon supports local file paths."""

    def test_local_path_supported(self):
        import asyncio

        import aiohttp
        from obs_widget import _fetch_hero_icon

        hero_info = {
            "icon_url": str(Path("assets/heroes_webp/antimage.webp").absolute())
        }

        async def run():
            session = aiohttp.ClientSession()
            try:
                return await _fetch_hero_icon(hero_info, session)
            finally:
                await session.close()

        img = asyncio.run(run())
        assert img is not None
        assert img.mode == "RGBA"
