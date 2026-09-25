"""One-off generator for assets/heroes_catalog.json.

Reads the raw OpenDota /heroes payload and writes the static catalog that
hero_meta falls back to when the API is rate limited. Run manually:

    python build_heroes_catalog.py path/to/opendota_heroes.json
"""
import json
import sys
from pathlib import Path

from hero_names import get_cdn_hero_name

OUT = Path(__file__).parent / "assets" / "heroes_catalog.json"
BASE = Path(__file__).parent / "assets" / "heroes_webp"


def main(src: str) -> None:
    payload = json.loads(Path(src).read_text(encoding="utf-8"))
    heroes = payload["result"] if isinstance(payload, dict) else payload

    catalog = {}
    for hero in heroes:
        short = hero["name"].replace("npc_dota_hero_", "")
        cdn = get_cdn_hero_name(short)
        catalog[str(hero["id"])] = {
            "name": hero["localized_name"],
            "short_name": short,
            "roles": hero.get("roles", []),
        }
        # Drop heroes we have no local art for, so the fallback never points at
        # a file that does not exist.
        if not (BASE / f"{cdn}.webp").exists():
            catalog.pop(str(hero["id"]), None)
            print(f"  skip {hero['id']} {short}: no local art")

    OUT.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Wrote {len(catalog)} heroes to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
