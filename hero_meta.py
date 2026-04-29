import asyncio
import requests
import io
from PIL import Image, ImageDraw, ImageFont, ImageOps
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, ContextTypes, CommandHandler
import os
import logging

logger = logging.getLogger(__name__)

# --- Hero Meta Banner ---

BACKGROUND_PATH = "background_new.png"

# Try different font paths for cross-platform compatibility
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",     # Linux (common)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", # Linux bold
    "/usr/share/fonts/TTF/DejaVuSans.ttf",                 # Alternative Linux
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",           # Alternative Linux bold
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", # Another Linux font
    "/System/Library/Fonts/Arial.ttf",                     # macOS
    "/Library/Fonts/Arial.ttf",                           # macOS alternative
    "C:/Windows/Fonts/arial.ttf",                          # Windows
    "C:/Windows/Fonts/Arial.ttf",                         # Windows alternative
]

FONT_PATH = None
for path in FONT_PATHS:
    try:
        ImageFont.truetype(path, 12)  # Test if font works
        FONT_PATH = path
        logger.info(f"Using font: {path}")
        break
    except Exception as e:
        logger.debug(f"Font not available: {path} - {e}")
        continue

if FONT_PATH is None:
    FONT_PATH = ImageFont.load_default()  # Fallback to default
    logger.warning("Using default PIL font as no system fonts found")

# ╨а╨░╤Б╤И╨╕╤А╨╡╨╜╨╜╤Л╨╣ ╤Б╨┐╨╕╤Б╨╛╨║ ID ╨│╨╡╤А╨╛╨╡╨▓ ╨┤╨╗╤П ╨║╨░╨╢╨┤╨╛╨╣ ╤А╨╛╨╗╨╕ (╤З╤В╨╛╨▒╤Л ╤В╨╛╤З╨╜╨╛ ╨╜╨░╨▒╤А╨░╨╗╨╛╤Б╤М ╨┐╨╛ 5)
# Строгое распределение героев по основным ролям Dota 2 (2026)
# Исключаем универсальных героев - только "чистые" представители каждой роли

ROLE_MAPPING = {
    "КЕРРИ": [
        # Основные керри (поздняя игра, фарм, драки)
        1,   # Anti-Mage
        6,   # Drow Ranger
        8,   # Juggernaut
        10,  # Morphling
        12,  # Phantom Assassin
        35,  # Sven
        36,  # Tiny
        41,  # Faceless Void
        42,  # Wraith King
        44,  # Phantom Lancer
        46,  # Templar Assassin
        54,  # Lifestealer
        62,  # Bloodseeker
        67,  # Spectre
        70,  # Ursa
        73,  # Alchemist
        80,  # Lone Druid
        93,  # Slardar
        94,  # Medusa
        95   # Troll Warlord
    ],

    "ХАРДЛЕЙНЕР": [
        # Герои, которые могут брать линии самостоятельно (оффлейн/мид)
        2,   # Axe
        7,   # Earthshaker
        14,  # Pudge
        16,  # Sand King
        28,  # Slardar (уже в керри, но может быть хардлейнером)
        29,  # Tidehunter
        33,  # Doom
        38,  # Beastmaster
        49,  # Dragon Knight
        51,  # Clockwerk
        65,  # Batrider
        69,  # Doom (дубликат)
        96,  # Centaur Warrunner
        102, # Abaddon
        107, # Earthshaker (дубликат)
        108, # Underlord
        110, # Phoenix
        123, # Hoodwink
        126, # Void Spirit
        127, # Snapfire
        128, # Mars
        129  # Dawnbreaker
    ],

    "МИДЕР": [
        # Чистые мидеры (средняя линия)
        11,  # Shadow Fiend
        13,  # Puck
        15,  # Razor
        17,  # Storm Spirit
        21,  # Windrunner
        22,  # Zeus
        25,  # Lina
        34,  # Tinker
        39,  # Queen of Pain
        43,  # Death Prophet
        45,  # Pugna
        47,  # Viper
        52,  # Leshrac
        59,  # Huskar
        83,  # Treant Protector
        86,  # Rubick
        106, # Ember Spirit
        113  # Arc Warden
    ],

    "ЧАСТИЧНАЯ ПОДДЕРЖКА": [
        # Герои, которые могут частично поддерживать (активные 4 позиции)
        9,   # Mirana
        18,  # Sniper
        27,  # Shadow Shaman
        40,  # Venomancer
        56,  # Clinkz
        57,  # Broodmother
        58,  # Bounty Hunter
        60,  # Night Stalker
        72,  # Gyrocopter
        81,  # Chaos Knight
        84,  # Ogre Magi
        85,  # Undying
        88,  # Nyx Assassin
        89,  # Naga Siren
        90,  # Keeper of the Light
        91,  # Io
        92,  # Visage
        101, # Skywrath Mage
        105, # Techies
        109, # Terrorblade
        112, # Winter Wyvern
        115, # Magnus
        121, # Grimstroke
        122  # Elder Titan
    ],

    "ПОЛНАЯ ПОДДЕРЖКА": [
        # Герои, специализирующиеся на поддержке (пассивные 5 позиции)
        3,   # Bane
        5,   # Crystal Maiden
        20,  # Vengeful Spirit
        37,  # Warlock
        50,  # Dazzle
        53,  # Nature's Prophet
        64,  # Jakiro
        68,  # Ancient Apparition
        77,  # Lich
        78,  # Lion
        79,  # Shadow Demon
        87,  # Disruptor
        103, # Elder Titan (дубликат)
        104, # Legion Commander
        111, # Oracle
        112, # Winter Wyvern (дубликат)
        119  # Dark Willow
    ]
}

def apply_fancy_style(img, size=(188, 100), radius=15, border_width=3):

    """╨Ю╨▒╤А╨╡╨╖╨░╨╡╤В, ╨╖╨░╨║╤А╤Г╨│╨╗╤П╨╡╤В ╤Г╨│╨╗╨╛╨▓ ╨╕ ╨┤╨╛╨▒╨░╨▓╨╗╤П╨╡╤В ╨╖╨╛╨╗╨╛╤В╤Г╤О ╨╛╨▒╨▓╨╛╨┤╨║╤Г ╨б╨Э╨Р╨а╨г╨Ц╨Ш"""

    # ╨б╨╜╨░╤З╨░╨╗╨░ ╤Б╨╛╨╖╨┤╨░╨╡╨╝ ╨╕╨╖╨╛╨▒╤А╨░╨╢╨╡╨╜╨╕╨╡ ╤Б ╨╛╨▒╨▓╨╛╨┤╨║╨╛╨╣ ╤Б╨╜╨░╤Р╨╕╨│╨╕

    # ╨Ю╨▒╤Й╨╕╨╣ ╤А╨░╨╖╨╝╨╡╤А ╨▒╤Г╨┤╨╡╤В size + 2*border_width ╤Б ╨║╨░╨╢╨┤╨╛╨╣ ╤Б╤В╨╛╤А╨╛╨╜╤Л

    outer_size = (size[0] + 2 * border_width, size[1] + 2 * border_width)

    

    # ╨Ю╨▒╤А╨╡╨╖╨░╨╡╨╝ ╨╕ ╨╝╨░╤Б╤И╤В╨░╨▒╨╕╤А╤Г╨╡╨╝ ╨╕╤Б╤Е╨╛╨┤╨╜╨╛╨╡ ╨╕╨╖╨╛╨▒╤А╨░╨╢╨╡╨╜╨╕╨╡ ╨┤╨╛ ╤Г╨║╨░╨╖╨░╨╜╨╜╨╛╨│╨╛ ╤А╨░╨╖╨╝╨╡╤А╨░

    img_scaled = img.resize(size, Image.Resampling.LANCZOS)
    
    # ╨б╨╛╨╖╨┤╨░╨╡╨╝ ╨╝╨░╤Б╨║╤Г ╨┤╨╗╤П ╨╖╨░╨║╤А╤Г╨│╨╗╨╡╨╜╨╜╤Л╤Е ╤Г╨│╨╗╨╛╨▓ ╨▓╨╜╤Г╤В╤А╨╡╨╜╨╜╨╡╨│╨╛ ╨╕╨╖╨╛╨▒╤А╨░╨╢╨╡╨╜╨╕╤П
    mask = Image.new('L', size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle((0, 0) + size, radius=radius, fill=255)
    
    # ╨б╨╛╨╖╨┤╨░╨╡╨╝ ╨▓╤Л╤Е╨╛╨┤╨╜╨╛╨╡ ╨╕╨╖╨╛╨▒╤А╨░╨╢╨╡╨╜╨╕╨╡ ╤Б ╨┐╤А╨╛╨╖╤А╨░╤З╨╜╤Л╨╝ ╤Д╨╛╨╜╨╛╨╝
    output = Image.new('RGBA', outer_size, (0, 0, 0, 0))
    
    # ╨Т╤Б╤В╨░╨▓╨╗╤П╨╡╨╝ ╨╝╨░╤Б╤И╤В╨░╨▒╨╕╤А╨╛╨▓╨░╨╜╨╜╨╛╨╡ ╨╕╨╖╨╛╨▒╤А╨░╨╢╨╡╨╜╨╕╨╡ ╨▓ ╤Ж╨╡╨╜╤В╤А (╤Б ╤Г╤З╨╡╤В╨╛╨╝ ╨╛╨▒╨▓╨╛╨┤╨║╨╕)
    output.paste(img_scaled, (border_width, border_width), mask=mask)
    
    # ╨а╨╕╤Б╤Г╨╡╨╝ ╨╛╨▒╨▓╨╛╨┤╨║╤Г ╨▓╨╛╨║╤А╤Г╨│ ╨▓╤Б╨╡╨│╨╛ ╨╕╨╖╨╛╨▒╤А╨░╨╢╨╡╨╜╨╕╤П
    draw_border = ImageDraw.Draw(output)
    draw_border.rounded_rectangle(
        (0, 0, outer_size[0]-1, outer_size[1]-1),
        radius=radius + border_width,  # ╨г╨▓╨╡╨╗╨╕╤З╨╕╨▓╨░╨╡╨╝ ╤А╨░╨┤╨╕╤Г╤Б ╨┤╨╗╤П ╨▓╨╜╨╡╤И╨╜╨╡╨╣ ╨╛╨▒╨▓╨╛╨┤╨║╨╕
        outline=(255, 204, 0), 
        width=border_width
    )
    
    return output
async def get_dota_data(tier_filter=None, days=7):

    """Получение статистики героев из OpenDota heroStats API

    Args:
        tier_filter: None (all pro), 1 (TI1-2), or 2 (TI3+) tournament tiers
        days: Number of days to look back (default 7 for weekly stats)

    Returns:
        Hero statistics from OpenDota heroStats API with built-in role statistics
    """
    try:
        # Use heroStats API which has built-in role statistics
        response = requests.get("https://api.opendota.com/api/heroStats", timeout=30)
        if response.status_code != 200:
            logger.error(f"heroStats API error: HTTP {response.status_code}")
            return None

        hero_stats = response.json()
        if not hero_stats:
            logger.error("No hero stats received from API")
            return None

        # If no tier filtering needed, return all data
        if tier_filter is None:
            return hero_stats

        # Filter heroes by minimum professional picks for reliability
        filtered_heroes = []
        for hero in hero_stats:
            pro_pick = hero.get('pro_pick', 0)
            if pro_pick >= 25:  # Minimum 25 pro picks for statistical significance
                filtered_heroes.append(hero)

        logger.info(f"Filtered to {len(filtered_heroes)} heroes with >=25 pro picks")
        return filtered_heroes

    except Exception as e:
        logger.error(f"OpenDota API error: {e}")
        return None

async def _get_hero_stats_by_tier(tier_filter):
    """Calculate hero statistics from pro matches filtered by tournament tier.
    
    tier_filter: 1 for TI1-2 (tier 1 or 2 leagues), 2 for TI3+ (tier 3+ leagues)
    """
    try:
        # Fetch recent pro matches (last 30 days worth)
        response = requests.get(
            "https://api.opendota.com/api/proMatches",
            params={"limit": 500},
            timeout=30
        )
        if response.status_code != 200:
            logger.error(f"Failed to fetch pro matches: {response.status_code}")
            return []
        
        pro_matches = response.json()
        
        # Group matches by league and determine tier
        league_tiers = {}
        tier1_2_match_ids = set()
        tier3plus_match_ids = set()
        
        for match in pro_matches:
            league_id = match.get('leagueid')
            if not league_id:
                continue
                
            # Determine tier if not already cached
            if league_id not in league_tiers:
                league_tier = _get_league_tier(league_id)
                league_tiers[league_id] = league_tier
            else:
                league_tier = league_tiers[league_id]
            
            match_id = match.get('match_id')
            if league_tier <= 2:
                tier1_2_match_ids.add(match_id)
            else:
                tier3plus_match_ids.add(match_id)
        
        # Select appropriate match IDs based on filter
        selected_match_ids = tier1_2_match_ids if tier_filter == 1 else tier3plus_match_ids
        
        if not selected_match_ids:
            logger.warning(f"No matches found for tier {tier_filter} filter")
            return []
        
        # Calculate hero statistics from filtered matches
        hero_stats = {}
        
        for match in pro_matches:
            match_id = match.get('match_id')
            if match_id not in selected_match_ids:
                continue
            
            # Process each player in the match
            players = match.get('players', [])
            if not players and 'radiant_team' in match:
                # Some match formats have different player structures
                continue
            
            radiant_win = match.get('radiant_win', False)
            
            for player in players:
                hero_id = player.get('hero_id')
                if not hero_id:
                    continue
                
                if hero_id not in hero_stats:
                    hero_stats[hero_id] = {
                        'id': hero_id,
                        'pro_win': 0,
                        'pro_pick': 0,
                        'pro_ban': 0
                    }
                
                hero_stats[hero_id]['pro_pick'] += 1
                
                # Determine if player won
                player_slot = player.get('player_slot', 0)
                is_radiant = player_slot < 128
                player_won = (is_radiant and radiant_win) or (not is_radiant and not radiant_win)
                
                if player_won:
                    hero_stats[hero_id]['pro_win'] += 1
        
        # Convert to list and add hero metadata
        result = list(hero_stats.values())
        
        # Fetch hero metadata (names, images)
        heroes_response = requests.get(
            "https://api.opendota.com/api/heroes",
            timeout=30
        )
        if heroes_response.status_code == 200:
            heroes_data = heroes_response.json()
            hero_map = {h['id']: h for h in heroes_data}
            
            for hero_stat in result:
                hero_id = hero_stat['id']
                if hero_id in hero_map:
                    hero_info = hero_map[hero_id]
                    hero_stat['localized_name'] = hero_info.get('localized_name', 'Unknown')
                    hero_stat['name'] = hero_info.get('name', '')
                    hero_stat['img'] = hero_info.get('img', '')
                    hero_stat['icon'] = hero_info.get('icon', '')
        
        logger.info(f"Calculated hero stats for tier {tier_filter} from {len(selected_match_ids)} matches")
        return result
        
    except Exception as e:
        logger.error(f"Error calculating tier-filtered hero stats: {e}", exc_info=True)
        return []

def _get_league_tier(league_id):
    """Get league tier (1-8) for a league ID.
    
    Uses cached data and falls back to API call.
    Tier 1-2 = TI1-2 (major tournaments), Tier 3+ = smaller tournaments.
    """
    # Common league tiers cache (major tournaments)
    known_tiers = {
        # TI tournaments
        2: 1,   # The International
        22: 1,  # TI2
        64: 1,  # TI3
        113: 1, # TI4
        257: 1, # TI5
        334: 1, # TI6
        450: 1, # TI7
        568: 1, # TI8
        686: 1, # TI9
        805: 1, # TI10
        1243: 1, # TI11
        1361: 1, # TI12
        
        # Major tournaments (Tier 1)
        16: 1,  # Frankfurt Major
        35: 1,  # Shanghai Major
        67: 1,  # Manila Major
        121: 1, # Boston Major
        194: 1, # Kiev Major
        282: 1, # Boston Major 2017
        377: 1, # Kiev Major 2017
        476: 1, # Birmingham Major 2018
        583: 1, # Bucharest Major 2018
        698: 1, # Chongqing Major 2019
        815: 1, # Kuala Lumpur Major 2019
        932: 1, # Leipzig Major 2019
        1047: 1, # AniMajor 2021
        1155: 1, # Stockholm Major 2021
        1263: 1, # Arlington Major 2022
        1371: 1, # Riyadh Major 2023
        
        # DPC Tours (Tier 1-2)
        17: 1,  # DPC 2018-2019
        36: 1,  # DPC 2019-2020
        122: 1, # DPC 2021
        283: 1, # DPC 2022
        378: 1, # DPC 2023
        477: 1, # DPC 2023-2024
        
        # Regional leagues (Tier 2-3)
        13: 2,  # StarLadder
        24: 2,  # EPIC League
        351: 2, # Dota Pit
        542: 2, # Ultras Dota Pro
    }
    
    if league_id in known_tiers:
        return known_tiers[league_id]
    
    # Default to Tier 3 for unknown leagues (conservative)
    return 3

def create_infographic(hero_stats, tier_filter=None):
    """Создайте инфографику 5x5 с лучшими героями по ролям (на 0.5X больше)
    
    Args:
        hero_stats: List of hero statistics
        tier_filter: None (all pro), 1 (TI1-2), or 2 (TI3+) tournament tiers
    
    Note: Statistics are based on professional matches from OpenDota.
    The /heroStats endpoint does not support filtering by tournament tier (TI1-2 vs TI3+).
    For Tier 1-2 only statistics, a different approach is used:
    - Fetch pro matches and filter by league.tier
    - Calculate win rates from filtered matches
    
    Returns:
        bytes: PNG image bytes suitable for embedding in digests
    """
    logger.info(f"Starting create_infographic generation (tier_filter={tier_filter})")
    if not os.path.exists(BACKGROUND_PATH):

        base = Image.new("RGBA", (1200, 800), (25, 25, 35, 255))

        bg_width, bg_height = 1200, 800

    else:

        base = Image.open(BACKGROUND_PATH).convert("RGBA")

        bg_width, bg_height = base.size
    

    draw = ImageDraw.Draw(base)

    

    # ╨в╨╡╨║╤Б╤В ╨┐╨░╤В╤З╨░ ╤Г╨┤╨░╨╗╤С╨╜ (╨▒╨╛╨╗╤М╤И╨╡ ╨╜╨╡ ╨╜╤Г╨╢╨╡╨╜)

    # 2. ╨а╨Р╨б╨з╨Х╨в ╨а╨Р╨Ч╨Ь╨Х╨а╨Ю╨Т - ╨г╨Т╨Х╨Ы╨Ш╨з╨Х╨Э╨Ш╨Х ╨Э╨Р 0.5X

    margin_x = 50

    margin_y = 215

    gap_between_cols = 15

    gap_between_rows = 0

    

    available_width = bg_width - 2 * margin_x

    total_gaps_width = 6 * gap_between_cols

    col_width = (available_width - total_gaps_width) // 5

    

    available_height = bg_height - margin_y - 10

    total_gaps_height = 6 * gap_between_rows

    row_height = (available_height - total_gaps_height) // 5

    

    # ╨г╨Т╨Х╨Ы╨Ш╨з╨Х╨Э╨Ш╨Х ╨Э╨Р 0.163X

    base_icon_height = row_height - 25

    increased_height = int(base_icon_height * 1.163)

    icon_height = min(increased_height, row_height - 5)

    

    start_x = margin_x + gap_between_cols

    start_y = margin_y
    
    # ╨Ц╨╕╤А╨╜╤Л╨╣ ╤И╤А╨╕╤Д╤В ╨┤╨╗╤П WINRATE
    try:
        font_wr = ImageFont.truetype(FONT_PATH, 27)
        # ╨Я╤А╨╛╨▒╤Г╨╡╨╝ ╨╜╨░╨╣╤В╨╕ ╨╢╨╕╤А╨╜╤Л╨╣ ╨▓╨░╤А╨╕╨░╨╜╤В
        for bold_name in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
            try:
                font_wr = ImageFont.truetype(bold_name, 20)
                break
            except:
                continue
    except:
        font_wr = ImageFont.load_default()

    # Define roles with their corresponding heroStats position numbers
    ROLE_POSITIONS = {
        "КЕРРИ": 1,   # Position 1 in heroStats - carry on safe lane
        "МИДЕР": 2,    # Position 2 in heroStats - mid lane
        "ХАРДЛЕЙНЕР": 3,    # Position 3 in heroStats - off lane/hard lane
        "ЧАСТИЧНАЯ ПОДДЕРЖКА": 4,   # Position 4 in heroStats - soft support
        "ПОЛНАЯ ПОДДЕРЖКА": 5    # Position 5 in heroStats - hard support
    }

    for col_idx, (role_name, position) in enumerate(ROLE_POSITIONS.items()):

        # Get all heroes that have stats for this position and are in the role mapping
        role_heroes = []
        role_hero_ids = set(ROLE_MAPPING.get(role_name, []))
        for hero in hero_stats:
            if hero.get('id') not in role_hero_ids:
                continue
            pick_field = f"{position}_pick"
            win_field = f"{position}_win"

            # Check if hero has stats for this position
            if hero.get(pick_field, 0) > 0:
                # Create a copy of hero data with position-specific stats
                hero_copy = hero.copy()
                hero_copy['pro_pick'] = hero.get(pick_field, 0)
                hero_copy['pro_win'] = hero.get(win_field, 0)
                role_heroes.append(hero_copy)

        # Filter heroes with minimum picks for this position
        MIN_POSITION_PICKS = 10  # Minimum picks for position-specific stats
        role_heroes = [h for h in role_heroes if h.get('pro_pick', 0) >= MIN_POSITION_PICKS]

        # Calculate win rate for this position
        for hero in role_heroes:
            pro_win = hero.get('pro_win', 0)
            pro_pick = hero.get('pro_pick', 0)
            hero['wr'] = (pro_win / pro_pick * 100) if pro_pick > 0 else 0

        # Sort by win rate and take top 5
        top_5 = sorted(role_heroes, key=lambda x: x['wr'], reverse=True)[:5]

        for row_idx, hero in enumerate(top_5):
            x = start_x + col_idx * (col_width + gap_between_cols)
            y = start_y + row_idx * (row_height + gap_between_rows)
            
            # ╨Ю╤А╨╕╨│╨╕╨╜╨░╨╗╤М╨╜╨░╤П ╨┐╤А╤П╨╝╨╛╤Г╨│╨╛╨╗╤М╨╜╨░╤П ╨╕╨║╨╛╨╜╨║╨░ ╤Б ╤Г╨▓╨╡╨╗╨╕╤З╨╡╨╜╨╕╨╡╨╝ 0.5X
            icon_url = "https://cdn.cloudflare.steamstatic.com" + hero['img']
            try:
                # Увеличиваем timeout и добавляем повторные попытки для загрузки изображений
                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        r = requests.get(icon_url, timeout=5)  # увеличиваем timeout до 5 секунд
                        r.raise_for_status()  # проверяем HTTP статус
                        break  # успех, выходим из цикла
                    except Exception as e:
                        if attempt == max_retries:
                            raise e  # последняя попытка не удалась
                        logger.debug(f"Failed to load hero image (attempt {attempt + 1}/{max_retries + 1}): {e}")
                        import time
                        time.sleep(0.5)  # небольшая пауза перед повтором
                icon_raw = Image.open(io.BytesIO(r.content)).convert("RGBA")
                
                # ╨Ь╨░╤Б╤И╤В╨░╨▒╨╕╤А╤Г╨╡╨╝ ╨┐╨╛ ╤Г╨▓╨╡╨╗╨╕╤З╨╡╨╜╨╜╨╛╨╣ ╨▓╤Л╤Б╨╛╤В╨╡ (0.5X ╨▒╨╛╨╗╤М╤И╨╡)
                scale = icon_height / icon_raw.height
                new_width = int(icon_raw.width * scale)
                new_height = icon_height
                
                if new_width > col_width:
                    scale = col_width / icon_raw.width
                    new_width = col_width
                    new_height = int(icon_raw.height * scale)
                
                icon_scaled = icon_raw.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # ╨Ш╤Б╨┐╨╛╨╗╤М╨╖╤Г╨╡╨╝ ╨│╨╛╤В╨╛╨▓╤Г╤О ╤Д╤Г╨╜╨║╤Ж╨╕╤О ╨┤╨╗╤П ╨╛╨▒╨▓╨╛╨┤╨║╨╕ ╨╕ ╨╖╨░╨║╤А╤Г╨│╨╗╨╡╨╜╨╕╤П
                # ╨б╨╜╨░╤З╨░╨╗╨░ ╨╝╨░╤Б╤И╤В╨░╨▒╨╕╤А╤Г╨╡╨╝ ╨╕╨║╨╛╨╜╨║╤Г
                icon_processed = apply_fancy_style(icon_scaled, size=(new_width, new_height), radius=max(8, new_height // 12), border_width=2)
                
                # ╨а╨░╨╖╨╝╨╡╤А ╨╛╨▒╤А╨░╨▒╨╛╤В╨░╨╜╨╜╨╛╨╣ ╨╕╨║╨╛╨╜╨║╨╕ ╤Б ╨▓╨╜╨╡╤И╨╜╨╡╨╣ ╨╛╨▒╨▓╨╛╨┤╨║╨╛╨╣
                processed_width = new_width + 4  # 2*border_width ╨│╨┤╨╡ border_width=2
                processed_height = new_height + 4
                
                # ╨Я╨╛╨╖╨╕╤Ж╨╕╤П ╨┐╨╛ ╤Ж╨╡╨╜╤В╤А╤Г ╨▓ ╨║╨╛╨╗╨╛╨╜╨║╨╡
                icon_x = x + (col_width - processed_width) // 2
                icon_y = y + 5
                base.paste(icon_processed, (icon_x, icon_y), icon_processed)
                
                # ╨в╨Х╨Ъ╨б╨в WINRATE ╨Т╨Э╨г╨в╨а╨Ш ╨Ш╨Ъ╨Ю╨Э╨Ъ╨Ш - ╨Т ╨ж╨Х╨Э╨в╨а╨Х ╨Т╨Э╨Ш╨Ч╨г (╨С╨Х╨Ч ╨з╨Х╨а╨Э╨Ю╨Щ ╨Я╨Ю╨Ф╨Ъ╨Ы╨Р╨Ф╨Ъ╨Ш!)
                wr_value = round(hero['wr'])
                wr_text = f"{wr_value}%"
                
                # ╨Я╨╛╨╖╨╕╤Ж╨╕╤П: ╨▓ ╤Б╨░╨╝╨╛╨╝ ╨╜╨╕╨╖╤Г ╨╛╤А╨╕╨│╨╕╨╜╨░╨╗╤М╨╜╨╛╨╣ ╨╕╨║╨╛╨╜╨║╨╕ (╨▒╨╡╨╖ ╨╛╨▒╨▓╨╛╨┤╨║╨╕), ╨┐╨╛ ╤Ж╨╡╨╜╤В╤А╤Г
                icon_center_x = icon_x + processed_width // 2  # ╨ж╨╡╨╜╤В╤А ╨╛╨▒╤А╨░╨▒╨╛╤В╨░╨╜╨╜╨╛╨╣ ╨╕╨║╨╛╨╜╨║╨╕
                icon_bottom_y = icon_y + new_height + 2 - 12   # ╨Э╨╕╨╖ ╨╛╤А╨╕╨│╨╕╨╜╨░╨╗╤М╨╜╨╛╨╣ ╨╕╨║╨╛╨╜╨║╨╕ + ╨╛╤В╤Б╤В╤Г╨┐ (new_height + 2*border_width - ╨╛╤В╤Б╤В╤Г╨┐)
                
                try:
                    # ╨Ш╤Б╨┐╨╛╨╗╤М╨╖╤Г╨╡╨╝ ╨╢╨╕╤А╨╜╤Л╨╣ ╤И╤А╨╕╤Д╤В ╨▒╨╛╨╗╤М╤И╨╡╨│╨╛ ╤А╨░╨╖╨╝╨╡╤А╨░ (╤Г╨▓╨╡╨╗╨╕╤З╨╡╨╜ ╨▓ 1.5 ╤А╨░╨╖╨░ ╨╛╤В ╨╛╤А╨╕╨│╨╕╨╜╨░╨╗╨░ 18pt = 27pt)
                    font_large = ImageFont.truetype(FONT_PATH, 30)
                    for bold_name in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
                        try:
                            font_large = ImageFont.truetype(f"C:/Windows/Fonts/{bold_name}", 30)
                            break
                        except:
                            continue
                except:
                    font_large = ImageFont.load_default()
                
                try:
                    bbox = draw.textbbox((0, 0), wr_text, font=font_large)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    
                    # ╨ж╨╡╨╜╤В╤А╨╕╤А╤Г╨╡╨╝ ╤В╨╡╨║╤Б╤В
                    text_x = icon_center_x - text_width // 2
                    text_y = icon_bottom_y - text_height
                    
                    # ╨Ю╤Б╨╜╨╛╨▓╨╜╨╛╨╣ ╤В╨╡╨║╤Б╤В ╨┐╨╛╨▓╨╡╤А╤Е

                    draw.text((text_x, text_y), wr_text, fill=(255, 255, 255), font=font_large)
                    
                except Exception:
                    # ╨Х╤Б╨╗╨╕ ╨╜╨╡ ╨┐╨╛╨╗╤Г╤З╨╕╨╗╨╛╤Б╤М - ╨┐╤А╨╛╤Б╤В╨╛ ╨╢╨╕╤А╨╜╤Л╨╣ ╤В╨╡╨║╤Б╤В
                    draw.text((icon_center_x - 20, icon_bottom_y - 20),
                             wr_text, fill=(255, 255, 255), font=font_large)
                    # ╨Х╤Б╨╗╨╕ ╨╜╨╡ ╨┐╨╛╨╗╤Г╤З╨╕╨╗╨╛╤Б╤М - ╨┐╤А╨╛╤Б╤В╨╛ ╨╢╨╕╤А╨╜╤Л╨╣ ╤В╨╡╨║╤Б╤В
                    draw.text((icon_center_x - 20, icon_bottom_y - 20),
                             wr_text, fill=(255, 255, 255), font=font_large)
                
            except Exception as e:
                # Placeholder
                draw.rounded_rectangle(
                    [x + 5, y + 5, x + col_width - 5, y + icon_height],
                    radius=10,
                    fill=(80, 80, 80)
                )

    buf = io.BytesIO()
    base.save(buf, format='PNG')
    return buf.getvalue()












async def get_hero_meta_image():
    """Generate hero meta image for external use (e.g., digests).

    Returns:
        bytes: PNG image bytes that can be embedded as a header,
               or None if generation failed.
    """
    logger.info("get_hero_meta_image called - starting generation")
    try:
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota")
            return None
        return create_infographic(data)
    except Exception as e:
        logger.warning(f"Failed to generate hero meta image: {e}")
        return None


def setup_hero_meta_job(application: Application):

    """╨Э╨░╤Б╤В╤А╨╛╨╣╨║╨░ ╨┐╨╗╨░╨╜╨╕╤А╨╛╨▓╤Й╨╕╨║╨░ ╨┤╨╗╤П ╨╡╨╢╨╡╨╜╨╡╨┤╨╡╨╗╤М╨╜╨╛╨│╨╛ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П ╨╝╨╡╤В╤Л ╨│╨╡╤А╨╛╨╡╨▓"""

    chat_id = os.getenv('HERO_META_CHAT_ID')

    if chat_id:

        try:

            application.bot_data['hero_meta_chat_id'] = int(chat_id)

            logger.info(f"Hero meta chat ID set to: {chat_id}")

        except ValueError:

            logger.warning(f"Invalid HERO_META_CHAT_ID: {chat_id}")

    else:

        logger.warning("HERO_META_CHAT_ID not set in environment variables")

    # Note: Weekly job and /meta command are available for hero meta updates
    logger.info("Hero meta setup completed")
