# -*- coding: utf-8 -*-
"""
Utility script to generate and save a weekly analytics chart for testing.

Usage:
    python generate_weekly_chart.py
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

sys.path.append('.')

from weekly_analytics import generate_weekly_analytics

__all__ = ["main"]


async def main(telegram_id: int = 123456789) -> dict[str, Any] | None:
    """Generate weekly analytics for the given telegram_id and save chart PNG if successful.
    Note: default 123456789 is a placeholder — use a real ID with match history for actual testing.
    """
    print("Generating weekly analytics...")
    data: dict[str, Any] | None = await generate_weekly_analytics(telegram_id)
    if data and 'image' in data:
        with open("weekly_chart.png", "wb") as f:
            f.write(data['image'])
        print("Chart saved as weekly_chart.png")
    else:
        print("Failed to generate chart")
    return data


if __name__ == "__main__":
    asyncio.run(main())