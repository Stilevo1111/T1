import asyncio
import aiohttp
import time

async def check():
    async with aiohttp.ClientSession() as session:
        for i in range(12):
            try:
                async with session.get('https://fissure-bot.onrender.com/api/steam-debug', timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 404:
                        print(f"Try {i+1}: {resp.status}")
                        print(await resp.text())
                        return
            except Exception as e:
                pass
            print(f"Try {i+1}: 404 or error")
            time.sleep(10)

asyncio.run(check())