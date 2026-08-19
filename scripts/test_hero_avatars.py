"""
Test generator: hero meta icons with best player avatar circles.
Not part of the bot - standalone script for visual testing.
"""

import io
import os
import sys
import time
import math
import asyncio
import aiohttp
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from database import get_connection, release_connection, get_db_type
from hero_meta import fetch_hero_icon
from hero_positions import hero_positions

# Config
AVATAR_SIZE = 40  # size of avatar circle
AVATAR_MARGIN = 8  # margin from top-right corner
OUTPUT_DIR = Path("test_meta_with_avatars")
OUTPUT_DIR.mkdir(exist_ok=True)

# Cache
_avatar_cache = {}
_avatar_cache_ttl = 3600  # 1 hour


def get_best_players_per_hero(limit_per_hero=3):
    """Get best players per hero from public_player_matches."""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        scheme = get_db_type()
        
        if "postgres" in scheme:
            query = """
                SELECT 
                    ppm.hero_id,
                    ppm.steam_id,
                    COUNT(*) as games,
                    SUM(CASE WHEN (ppm.player_slot < 128 AND ppm.radiant_win = 1) OR (ppm.player_slot >= 128 AND ppm.radiant_win = 0) THEN 1 ELSE 0 END) as wins,
                    u.mmr,
                    u.steam_nickname,
                    u.avatar
                FROM public_player_matches ppm
                LEFT JOIN users u ON ppm.steam_id = u.steam_id
                WHERE ppm.start_time > %s
                GROUP BY ppm.hero_id, ppm.steam_id, u.mmr, u.steam_nickname, u.avatar
                ORDER BY ppm.hero_id, wins DESC, games DESC
            """
            week_ago = int(time.time()) - (7 * 24 * 3600)
            cursor.execute(query, (week_ago,))
        else:
            query = """
                SELECT 
                    ppm.hero_id,
                    ppm.steam_id,
                    COUNT(*) as games,
                    SUM(CASE WHEN (ppm.player_slot < 128 AND ppm.radiant_win = 1) OR (ppm.player_slot >= 128 AND ppm.radiant_win = 0) THEN 1 ELSE 0 END) as wins,
                    u.mmr,
                    u.steam_nickname,
                    u.avatar
                FROM public_player_matches ppm
                LEFT JOIN users u ON ppm.steam_id = u.steam_id
                WHERE ppm.start_time > ?
                GROUP BY ppm.hero_id, ppm.steam_id, u.mmr, u.steam_nickname, u.avatar
                ORDER BY ppm.hero_id, wins DESC, games DESC
            """
            week_ago = int(time.time()) - (7 * 24 * 3600)
            cursor.execute(query, (week_ago,))
        
        rows = cursor.fetchall()
        cursor.close()
        
        # Group by hero_id and take top N players
        best_players = {}
        for row in rows:
            hero_id = row[0]
            if hero_id not in best_players:
                best_players[hero_id] = []
            if len(best_players[hero_id]) < limit_per_hero:
                best_players[hero_id].append({
                    'hero_id': hero_id,
                    'steam_id': row[1],
                    'games': row[2],
                    'wins': row[3],
                    'mmr': row[4] or 0,
                    'nickname': row[5] or f"Player {row[1]}",
                    'avatar': row[6],
                    'winrate': (row[3] / row[2] * 100) if row[2] > 0 else 0
                })
        
        return best_players
    finally:
        if conn:
            release_connection(conn)


async def fetch_avatar(session, avatar_url, steam_id):
    """Fetch Steam avatar with cache."""
    if not avatar_url:
        return None
    
    now = time.time()
    cached = _avatar_cache.get(avatar_url)
    if cached and (now - cached[1]) < _AVATAR_CACHE_TTL:
        return cached[0]
    
    try:
        async with session.get(
            avatar_url,
            timeout=aiohttp.ClientTimeout(total=6),
            headers={"User-Agent": "Mozilla/5.0"}
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            _avatar_cache[avatar_url] = (img, now)
            return img
    except Exception as e:
        print(f"Failed to fetch avatar for {steam_id}: {e}")
        return None


def create_avatar_circle(avatar_img, size=AVATAR_SIZE):
    """Create circular avatar from square image."""
    if avatar_img is None:
        # Return placeholder
        placeholder = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(placeholder)
        draw.ellipse([0, 0, size-1, size-1], fill=(100, 100, 100, 255))
        return placeholder
    
    # Resize to square
    avatar_img = avatar_img.resize((size, size), Image.Resampling.LANCZOS)
    
    # Create circular mask
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([0, 0, size-1, size-1], fill=255)
    
    # Apply mask
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(avatar_img, (0, 0), mask)
    
    # Add white border
    border = Image.new("RGBA", (size + 4, size + 4), (0, 0, 0, 0))
    border_mask = Image.new("L", (size + 4, size + 4), 0)
    draw_border = ImageDraw.Draw(border_mask)
    draw_border.ellipse([0, 0, size + 3, size + 3], fill=255)
    border.paste(output, (2, 2), mask)
    
    return border


async def generate_test_image(hero_id, hero_icon, best_players):
    """Generate test hero icon with avatar circle."""
    if hero_icon is None:
        return None
    
    # Get best player for this hero
    players = best_players.get(hero_id, [])
    best_player = players[0] if players else None
    
    # Create copy of hero icon
    result = hero_icon.copy().convert("RGBA")
    
    if best_player and best_player.get('avatar'):
        # Fetch avatar
        async with aiohttp.ClientSession() as session:
            avatar_img = await fetch_avatar(session, best_player['avatar'], best_player['steam_id'])
        
        if avatar_img:
            # Create avatar circle
            avatar_circle = create_avatar_circle(avatar_img, AVATAR_SIZE)
            
            # Position in top-right corner with margin
            icon_width, icon_height = result.size
            x = icon_width - AVATAR_SIZE - AVATAR_MARGIN - 2  # -2 for border
            y = AVATAR_MARGIN + 2
            
            # Paste avatar circle
            result.paste(avatar_circle, (x, y), avatar_circle)
    
    return result


async def main():
    print("Starting test generator...")
    
    # Get best players per hero
    print("Loading best players per hero from database...")
    best_players = get_best_players_per_hero(limit_per_hero=3)
    print(f"Found best players for {len(best_players)} heroes")
    
    # Get hero stats (for hero IDs)
    from hero_meta import get_hero_stats
    hero_stats = get_hero_stats()
    if not hero_stats:
        print("No hero stats available")
        return
    
    print(f"Processing {len(hero_stats)} heroes...")
    
    # Process each hero
    async with aiohttp.ClientSession() as session:
        for i, hero in enumerate(hero_stats[:10]):  # Test first 10 heroes
            hero_id = hero.get('hero_id', hero.get('id'))
            hero_name = hero.get('localized_name', hero.get('name', f'Hero {hero_id}'))
            
            print(f"[{i+1}/10] Processing {hero_name} (ID: {hero_id})")
            
            # Fetch hero icon
            hero_icon = await fetch_hero_icon(session, hero.get('img'))
            if hero_icon is None:
                print(f"  No icon for {hero_name}")
                continue
            
            # Generate test image with avatar
            test_img = await generate_test_image(hero_id, hero_icon, best_players)
            if test_img is None:
                continue
            
            # Save
            safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in hero_name)
            output_path = OUTPUT_DIR / f"{hero_id}_{safe_name}.png"
            test_img.save(output_path, "PNG")
            print(f"  Saved: {output_path}")
            
            # Show best player info
            players = best_players.get(hero_id, [])
            if players:
                best = players[0]
                print(f"  Best player: {best['nickname']} (MMR: {best['mmr']}, WR: {best['winrate']:.1f}%, {best['games']} games)")
    
    print(f"\nDone! Test images saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
