"""Tests for the hero meta infographic.

The infographic used to come out empty because the hero catalog came from the
OpenDota API, whose only cache is a plain in-process dict. After a deploy the
first /heroes call hits the rate limit, callers get no names, roles or image
paths, every hero collapses into the SUPPORT column, and the missing icons
short-circuited the loop that draws player avatars.

These tests pin the local catalog fallback and the avatar behaviour.
"""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import dota_mmr  # noqa: E402
import hero_meta  # noqa: E402


def test_local_catalog_covers_every_hero_with_local_art():
    """Every catalog entry must point at art that actually exists on disk."""
    catalog = dota_mmr.get_local_heroes_data()
    assert len(catalog) > 100, f"catalog looks too small: {len(catalog)}"

    for hero_id, hero in catalog.items():
        assert isinstance(hero_id, int), "ids must be ints to match the DB"
        assert hero["name"], f"hero {hero_id} has no name"
        assert hero["roles"], f"hero {hero_id} has no roles"
        assert Path(hero["img"]).exists(), f"missing art for {hero['name']}"


def test_heroes_data_falls_back_to_local_catalog(monkeypatch):
    """A refused API call must still yield a usable catalog."""
    import asyncio

    async def offline(url, *args, **kwargs):
        return None

    monkeypatch.setattr(dota_mmr, "_api_get_async", offline)
    monkeypatch.setattr(dota_mmr, "_get_cached", lambda key: None)

    heroes = asyncio.run(dota_mmr.get_heroes_data_async())

    assert len(heroes) > 100
    assert Path(heroes[1]["img"]).exists()


def test_roles_spread_heroes_across_positions():
    """Empty roles used to send every hero to SUPPORT, blanking four columns."""
    heroes = dota_mmr.get_local_heroes_data()

    by_position = {}
    for hero in heroes.values():
        pos = hero_meta.detect_hero_position(
            {"localized_name": hero["name"], "roles": hero["roles"]}
        )
        by_position.setdefault(pos, []).append(hero["name"])

    assert len(by_position) >= 4, f"positions collapsed: {sorted(by_position)}"
    # No single position may swallow the whole roster.
    assert max(len(v) for v in by_position.values()) < len(heroes) * 0.5


def _grid():
    return {
        pos: [{
            "id": hero_id, "name": f"H{hero_id}", "img": "",
            "winrate": 0.6, "pub_win": 10, "pub_losses": 5,
        }]
        for pos, hero_id in zip(range(1, 6), [1, 8, 129, 84, 65])
    }


def _render(icons, avatars):
    base = Image.new("RGBA", (1200, 800), (25, 25, 35, 255))
    hero_meta._compose_infographic(
        base, ImageDraw.Draw(base), _grid(), icons,
        hero_meta.ImageFont.load_default(), 50, 215, 15, 202, 115, 104, avatars,
    )
    return base


def _red_avatar():
    img = Image.new("RGBA", (40, 40), (255, 0, 0, 255))
    mask = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 39, 39], fill=255)
    img.putalpha(mask)
    return img


def test_avatar_is_drawn_when_the_hero_icon_is_missing():
    """A failed icon lookup must not hide the player avatar.

    This was the `continue` in the missing-icon branch: it skipped the avatar
    circle entirely, so one failure removed all avatars from the banner.
    """
    avatars = {h: _red_avatar() for h in (1, 8, 129, 84, 65)}
    rendered = _render({}, avatars).convert("RGB")

    reds = sum(1 for r, g, b in rendered.getdata() if r > 200 and g < 80 and b < 80)
    assert reds > 500, f"avatar pixels missing, found only {reds}"


def test_real_hero_icon_is_drawn_when_available():
    icon_bytes = dota_mmr.get_hero_icon_cached("antimage")
    assert icon_bytes, "expected a local icon for antimage"
    icon = Image.open(io.BytesIO(icon_bytes)).convert("RGBA")

    base = _render({1: icon}, {})
    crop = base.crop((50, 215, 252, 330)).convert("RGB")
    colors = len(crop.getcolors(maxcolors=100000) or [])

    placeholder = _render({}, {}).crop((50, 215, 252, 330)).convert("RGB")
    placeholder_colors = len(placeholder.getcolors(maxcolors=100000) or [])

    assert colors > placeholder_colors, "real icon did not render"


@pytest.mark.parametrize("hero_id", [1, 8, 129, 84, 65])
def test_bundled_icons_match_the_catalog(hero_id):
    """Each hero in the catalog resolves to a file we actually ship."""
    hero = dota_mmr.get_local_heroes_data()[hero_id]
    assert Path(hero["icon_url"]).exists()
    assert Path(hero["image_url"]).exists()
