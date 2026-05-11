import asyncio
import sys
import os
sys.path.append('.')

from weekly_analytics import generate_weekly_analytics

async def main():
    telegram_id = 123456789  # example, but need a real one with data
    print("Generating weekly analytics...")
    data = await generate_weekly_analytics(telegram_id)
    if data and 'image' in data:
        with open("weekly_chart.png", "wb") as f:
            f.write(data['image'])
        print("Chart saved as weekly_chart.png")
    else:
        print("Failed to generate chart")

if __name__ == "__main__":
    asyncio.run(main())