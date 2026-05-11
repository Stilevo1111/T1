import asyncio
import sys
import os
import traceback
sys.path.append('.')

from hero_meta import get_hero_meta_image

async def main():
    print("Generating hero meta banner...")
    try:
        banner = await get_hero_meta_image()
        if banner:
            with open("digest_banner.png", "wb") as f:
                f.write(banner)
            print("Banner saved as digest_banner.png")
        else:
            print("Failed to generate banner")
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())