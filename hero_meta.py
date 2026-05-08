import asyncio

import aiohttp

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
        29,  # Tidehunter
        33,  # Doom
        38,  # Beastmaster
        49,  # Dragon Knight
        51,  # Clockwerk
        65,  # Batrider
        96,  # Centaur Warrunner
        102, # Abaddon
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
        104, # Legion Commander
        111, # Oracle
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

async def get_weekly_hero_stats():
    """Получение недельной статистики героев из матчей OpenDota за последние 7 дней"""
    try:
        from datetime import datetime, timedelta

        # Получаем матчи за последние 7 дней
        start_time = int((datetime.now() - timedelta(days=7)).timestamp())

        # Запрашиваем матчи с retry на ошибки 522
        matches = []
        url = f"https://api.opendota.com/api/matches?date=7&limit=200"
        max_retries = 3  # уменьшено с 5 до 3 для экономии времени

        timeout = aiohttp.ClientTimeout(total=10)  # уменьшено до 10 секунд на запрос

        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            data = await response.json()
                            matches.extend(data)
                            logger.info(f"Fetched {len(matches)} matches for weekly stats on attempt {attempt + 1}")
                            break
                        elif response.status in [429, 500, 502, 503, 504, 522]:
                            logger.warning(f"Matches API {response.status} on attempt {attempt + 1}, retrying...")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** (attempt + 1))  # 2, 4, 8 секунд вместо 5,10,20
                                continue
                            else:
                                logger.error(f"Matches API failed after {max_retries} attempts")
                                return None
                        else:
                            logger.error(f"Matches API error: HTTP {response.status}")
                            return None
            except Exception as e:
                logger.warning(f"Matches API request error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** (attempt + 1))  # 2, 4, 8 секунд
                    continue
                else:
                    logger.error(f"Matches API failed after retries: {e}")
                    return None

        if not matches:
            return None

        # Агрегируем статистику героев
        hero_stats = {}
        for match in matches:
            if not match.get('players'):
                continue

            radiant_win = match.get('radiant_win', False)
            for player in match['players']:
                hero_id = player.get('hero_id')
                if not hero_id:
                    continue

                if hero_id not in hero_stats:
                    hero_stats[hero_id] = {'wins': 0, 'picks': 0}

                hero_stats[hero_id]['picks'] += 1
                if (player['isRadiant'] and radiant_win) or (not player['isRadiant'] and not radiant_win):
                    hero_stats[hero_id]['wins'] += 1

        # Преобразуем в формат heroStats
        hero_list = []
        for hero_id, stats in hero_stats.items():
            if stats['picks'] >= 10:
                winrate = (stats['wins'] / stats['picks']) * 100
                hero_list.append({
                    'id': hero_id,
                    'localized_name': f'Hero {hero_id}',
                    'pro_win': stats['wins'],
                    'pro_pick': stats['picks'],
                    'wr': winrate,
                    'img': f'https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/{hero_id}.png'
                })

        logger.info(f"Calculated weekly stats for {len(hero_list)} heroes")
        return hero_list

    except Exception as e:
        logger.error(f"Weekly hero stats error: {e}")
        return await get_fallback_hero_stats()


async def get_fallback_hero_stats():
    """Fallback: получение накопительной статистики героев из OpenDota heroStats API"""
    try:
        url = "https://api.opendota.com/api/heroStats"
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    logger.error(f"Fallback heroStats API error: HTTP {response.status}")
                    return None

                hero_stats = await response.json()
                if not hero_stats:
                    logger.error("No hero stats received from fallback API")
                    return None

        # Преобразуем в нужный формат
        hero_list = []
        for hero in hero_stats:
            pro_win = hero.get('pro_win', 0)
            pro_pick = hero.get('pro_pick', 0)
            if pro_pick >= 50:  # Фильтр как в оригинале
                wr = (pro_win / pro_pick * 100) if pro_pick > 0 else 0
                hero_list.append({
                    'id': hero['id'],
                    'localized_name': hero.get('localized_name', f'Hero {hero["id"]}'),
                    'pro_win': pro_win,
                    'pro_pick': pro_pick,
                    'wr': wr,
                    'img': "https://cdn.cloudflare.steamstatic.com" + hero.get('img', '')
                })

        logger.info(f"Fallback: loaded {len(hero_list)} heroes from heroStats")
        return hero_list

    except Exception as e:
        logger.error(f"Fallback hero stats error: {e}")
        return None


async def get_dota_data(days=7):
    """Получение недельной статистики героев с fallback"""
    return await get_weekly_hero_stats()


async def fetch_hero_icon(session, icon_url, max_retries=2):
    """Асинхронная загрузка иконки героя с retry-логикой"""
    for attempt in range(max_retries + 1):
        try:
            async with session.get(icon_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                response.raise_for_status()
                content = await response.read()
                return Image.open(io.BytesIO(content)).convert("RGBA")
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"Failed to load hero image after {max_retries + 1} attempts: {e}")
                raise e
            logger.debug(f"Failed to load hero image (attempt {attempt + 1}/{max_retries + 1}): {e}")
            await asyncio.sleep(0.5)


async def create_infographic(hero_stats):
    """Создайте инфографику 5x5 с лучшими героями по ролям (на 0.5X больше)

    Args:
        hero_stats: List of hero statistics from OpenDota heroStats API

    Note: Statistics are based on professional matches from OpenDota.
    The /heroStats endpoint provides built-in role statistics.
    """
    logger.info("Starting create_infographic generation")

    # Загружаем фон (синхронно, это быстро)
    if not os.path.exists(BACKGROUND_PATH):
        base = Image.new("RGBA", (1200, 800), (25, 25, 35, 255))
        bg_width, bg_height = 1200, 800
    else:
        base = Image.open(BACKGROUND_PATH).convert("RGBA")
        bg_width, bg_height = base.size

    draw = ImageDraw.Draw(base)

    # Add update date in top right corner
    from datetime import datetime, timezone, timedelta
    MSK = timezone(timedelta(hours=3))
    now_msk = datetime.now(MSK)
    date_text = now_msk.strftime("%d.%m.%Y %H:%M")
    try:
        date_font = ImageFont.truetype(FONT_PATH, 24)
    except:
        date_font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), date_text, font=date_font)
    text_width = bbox[2] - bbox[0]
    text_x = bg_width - text_width - 20
    text_y = 20
    draw.text((text_x, text_y), date_text, fill=(255, 255, 255), font=date_font)

    # Параметры размещения
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

    base_icon_height = row_height - 25
    increased_height = int(base_icon_height * 1.163)
    icon_height = min(increased_height, row_height - 5)

    start_x = margin_x + gap_between_cols
    start_y = margin_y

    # Шрифт для winrate
    try:
        font_wr = ImageFont.truetype(FONT_PATH, 27)
        for bold_name in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
            try:
                font_wr = ImageFont.truetype(bold_name, 20)
                break
            except:
                continue
    except:
        font_wr = ImageFont.load_default()

    # Получаем топ-25 героев по overall win rate
    all_heroes = []
    for hero in hero_stats:
        pro_win = hero.get('pro_win', 0)
        pro_pick = hero.get('pro_pick', 0)
        if pro_pick >= 50:
            hero_copy = hero.copy()
            hero_copy['wr'] = (pro_win / pro_pick * 100) if pro_pick > 0 else 0
            all_heroes.append(hero_copy)

    top_25 = sorted(all_heroes, key=lambda x: x['wr'], reverse=True)[:25]

    # Асинхронно загружаем все иконки параллельно
    async with aiohttp.ClientSession() as session:
        icon_tasks = []
        for hero in top_25:
            icon_url = "https://cdn.cloudflare.steamstatic.com" + hero['img']
            task = fetch_hero_icon(session, icon_url)
            icon_tasks.append((hero, task))

        # Ждем все загрузки
        icon_results = []
        for hero, task in icon_tasks:
            try:
                icon_raw = await task
                icon_results.append((hero, icon_raw))
            except Exception as e:
                logger.warning(f"Failed to load icon for hero {hero.get('id')}: {e}")
                icon_results.append((hero, None))

    # Отрисовываем каждого героя
    for idx, (hero, icon_raw) in enumerate(icon_results):
        col_idx = idx % 5
        row_idx = idx // 5

        x = start_x + col_idx * (col_width + gap_between_cols)
        y = start_y + row_idx * (row_height + gap_between_rows)

        if icon_raw is None:
            # Placeholder при ошибке загрузки
            draw.rounded_rectangle(
                [x + 5, y + 5, x + col_width - 5, y + icon_height],
                radius=10,
                fill=(80, 80, 80)
            )
            continue

        # Масштабирование иконки
        scale = icon_height / icon_raw.height
        new_width = int(icon_raw.width * scale)
        new_height = icon_height

        if new_width > col_width:
            scale = col_width / icon_raw.width
            new_width = col_width
            new_height = int(icon_raw.height * scale)

        icon_scaled = icon_raw.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Применяем стиль
        icon_processed = apply_fancy_style(icon_scaled, size=(new_width, new_height), radius=max(8, new_height // 12), border_width=2)

        processed_width = new_width + 4
        processed_height = new_height + 4

        # Позиционирование
        icon_x = x + (col_width - processed_width) // 2
        icon_y = y + 5

        base.paste(icon_processed, (icon_x, icon_y), icon_processed)

        # Текст winrate
        wr_value = round(hero['wr'])
        wr_text = f"{wr_value}%"

        try:
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
            text_x = icon_x + processed_width // 2 - text_width // 2
            text_y = icon_y + new_height + 2 - 12 - text_height
            draw.text((text_x, text_y), wr_text, fill=(255, 255, 255), font=font_large)
        except Exception:
            draw.text((icon_x + processed_width // 2 - 20, icon_y + new_height + 2 - 12 - 20),
                     wr_text, fill=(255, 255, 255), font=font_large)

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
        return await create_infographic(data)
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
