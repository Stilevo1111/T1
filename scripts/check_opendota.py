import aiohttp
import asyncio
import sys

async def check():
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get('https://api.opendota.com/api/health') as resp:
                text = await resp.text()
                print(f"status={resp.status}")
                print(text[:500])
                sys.exit(0 if resp.status == 200 else 1)
    except Exception as e:
        print(f"error={e}")
        sys.exit(2)

asyncio.run(check())
