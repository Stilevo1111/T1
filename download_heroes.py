import asyncio
import aiohttp
import os

from dota_mmr import OPENDOTA_API_URL, _api_get_async

async def main():

    heroes = await _api_get_async(
        f"{OPENDOTA_API_URL}/heroes"
    )

    os.makedirs("assets/heroes", exist_ok=True)

    async with aiohttp.ClientSession() as session:

        for h in heroes:

            name = h["name"].replace(
                "npc_dota_hero_",
                ""
            )

            url = (
                "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/"
                f"dota_react/heroes/icons/{name}.png"
            )

            try:

                async with session.get(url) as r:

                    if r.status == 200:

                        data = await r.read()

                        with open(
                            f"assets/heroes/{name}.png",
                            "wb"
                        ) as f:
                            f.write(data)

                        print("Downloaded:", name)

            except:
                print("Failed:", name)

asyncio.run(main())