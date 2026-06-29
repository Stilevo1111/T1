# Асинхронная версия hero_meta.py с fallback и быстрым отказом

import asyncio

import aiohttp

import io

from PIL import Image, ImageDraw, ImageFont, ImageOps

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, Update

from telegram.ext import Application, ContextTypes, CommandHandler

import os

import logging

from urllib.parse import urlparse

logger = logging.getLogger(__name__)


BACKGROUND_PATH = "images/banners/heroes_strip.webp"

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/Arial.ttf",
]

FONT_PATH = None
for path in FONT_PATHS:
    try:
        ImageFont.truetype(path, 12)
        FONT_PATH = path
        logger.info(f"Using font: {path}")
        break
    except Exception as e:
        logger.debug(f"Font not available: {path} - {e}")
        continue

if FONT_PATH is None:
    FONT_PATH = ImageFont.load_default()
    logger.warning("Using default PIL font as no system fonts found")


ROLE_MAPPING = {
    "КЕРРИ": [1, 6, 8, 10, 12, 35, 36, 41, 42, 44, 46, 54, 62, 67, 70, 73, 80, 93, 94, 95],
    "ХАРДЛЕЙНЕР": [2, 7, 14, 16, 29, 33, 38, 49, 51, 65, 96, 102, 108],
}


def apply_fancy_style(img, size=(188, 100), radius=15, border_width=3):
    """Обрезка, закругление и добавление золотой обводки"""
    outer_size = (size[0] + 2 * border_width, size[1] + 2 * border_width)
    img_scaled = img.resize(size, Image.Resampling.LANCZOS)
    mask = Image.new('L', size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle((0, 0) + size, radius=radius, fill=255)
    output = Image.new('RGBA', outer_size, (0, 0, 0, 0))
    output.paste(img_scaled, (border_width, border_width), mask=mask)
    draw_border = ImageDraw.Draw(output)
    draw_border.rounded_rectangle(
        (0, 0) + outer_size,
        radius=radius,
        outline=(255, 215, 0, 255),
        width=2
    )
    return output


async def fetch_hero_icon(session, icon_path, max_retries=2):
    """Асинхронная загрузка иконки героя с retry-логикой"""
    # Ensure proper URL format
    if icon_path.startswith('/'):
        icon_url = f"https://cdn.cloudflare.steamstatic.com{icon_path}"
    elif not icon_path.startswith('http'):
        icon_url = f"https://cdn.cloudflare.steamstatic.com/{icon_path}"
    else:
        icon_url = icon_path

    for attempt in range(max_retries + 1):
        try:
            async with session.get(icon_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                response.raise_for_status()
                content = await response.read()
                return Image.open(io.BytesIO(content)).convert("RGBA")
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"Failed to load hero image after {max_retries + 1} attempts: {e!r}")
                raise e
            logger.debug(f"Failed to load hero image (attempt {attempt + 1}/{max_retries + 1}): {e!r}")
            await asyncio.sleep(0.5)


async def get_weekly_hero_stats():
    """Получение недельной статистики героев из матчей OpenDota за последние 7 дней"""
    try:
        from datetime import datetime, timedelta

        start_time = int((datetime.now() - timedelta(days=7)).timestamp())

        matches = []
        url = f"https://api.opendota.com/api/matches?date=7&limit=200"
        max_retries = 1
        timeout = aiohttp.ClientTimeout(total=5)

        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            data = await response.json()
                            matches.extend(data)
                            logger.info(f"Fetched {len(matches)} matches for weekly stats on attempt {attempt + 1}")
                            break
                        else:
                            logger.error(f"Matches API error: HTTP {response.status}")
                            break
            except Exception as e:
                logger.warning(f"Matches API request error on attempt {attempt + 1}: {e!r}")
                break

        if not matches:
            logger.warning("No matches from weekly stats, trying fallback")
            return await get_fallback_hero_stats()

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
                    'img': f"/apps/dota2/images/dota_react/heroes/icons/{hero_id}.png"
                })

        logger.info(f"Calculated weekly stats for {len(hero_list)} heroes")
        return hero_list

    except Exception as e:
        logger.error(f"Weekly hero stats error: {e!r}")
        return await get_fallback_hero_stats()


async def get_fallback_hero_stats():
    """Fallback: получение накопительной статистики героев из OpenDota heroStats API"""
    try:
        url = "https://api.opendota.com/api/heroStats"
        timeout = aiohttp.ClientTimeout(total=5)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    logger.error(f"Fallback heroStats API error: HTTP {response.status}")
                    raise Exception(f"HTTP {response.status}")
                hero_stats = await response.json()
                if not hero_stats:
                    logger.error("No hero stats received from fallback API")
                    raise Exception("Empty response")

        hero_list = []
        for hero in hero_stats:
            pro_win = hero.get('pro_win', 0)
            pro_pick = hero.get('pro_pick', 0)
            if pro_pick >= 50:
                wr = (pro_win / pro_pick * 100) if pro_pick > 0 else 0
                img_path = hero.get('img', '')
                # Normalize image path: ensure it starts with / and is relative
                if img_path.startswith('http'):
                    # Extract path from URL
                    from urllib.parse import urlparse
                    parsed = urlparse(img_path)
                    img_path = parsed.path
                if not img_path.startswith('/'):
                    img_path = '/' + img_path
                hero_list.append({
                    'id': hero['id'],
                    'localized_name': hero.get('localized_name', f'Hero {hero["id"]}'),
                    'pro_win': pro_win,
                    'pro_pick': pro_pick,
                    'wr': wr,
                    'img': img_path
                })

        logger.info(f"Fallback: loaded {len(hero_list)} heroes from heroStats")
        return hero_list

    except Exception as e:
        logger.error(f"Fallback hero stats error: {e!r}")
        return None


async def get_dota_data(days=7):
    """Получение недельной статистики героев с fallback"""
    return await get_weekly_hero_stats()


async def create_infographic(hero_stats):
    """Создайте инфографику 5x5 с лучшими героями по ролям"""
    logger.info("Starting create_infographic generation")

    if not os.path.exists(BACKGROUND_PATH):
        base = Image.new("RGBA", (1200, 800), (25, 25, 35, 255))
        bg_width, bg_height = 1200, 800
    else:
        base = Image.open(BACKGROUND_PATH).convert("RGBA")
        bg_width, bg_height = base.size

    draw = ImageDraw.Draw(base)

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

    all_heroes = []
    for hero in hero_stats:
        pro_win = hero.get('pro_win', 0)
        pro_pick = hero.get('pro_pick', 0)
        if pro_pick >= 50:
            hero_copy = hero.copy()
            hero_copy['wr'] = (pro_win / pro_pick * 100) if pro_pick > 0 else 0
            all_heroes.append(hero_copy)

    top_25 = sorted(all_heroes, key=lambda x: x['wr'], reverse=True)[:25]

    async with aiohttp.ClientSession() as session:
        icon_tasks = []
        for hero in top_25:
            task = fetch_hero_icon(session, hero['img'])
            icon_tasks.append((hero, task))

        icon_results = []
        for hero, task in icon_tasks:
            try:
                icon_raw = await task
                icon_results.append((hero, icon_raw))
            except Exception as e:
                logger.warning(f"Failed to load icon for hero {hero.get('id')}: {e!r}")
                icon_results.append((hero, None))

    for idx, (hero, icon_raw) in enumerate(icon_results):
        col_idx = idx % 5
        row_idx = idx // 5

        x = start_x + col_idx * (col_width + gap_between_cols)
        y = start_y + row_idx * (row_height + gap_between_rows)

        if icon_raw is None:
            draw.rounded_rectangle(
                [x + 5, y + 5, x + col_width - 5, y + icon_height],
                radius=10,
                fill=(80, 80, 80)
            )
            continue

        scale = icon_height / icon_raw.height
        new_width = int(icon_raw.width * scale)
        new_height = icon_height

        if new_width > col_width:
            scale = col_width / icon_raw.width
            new_width = col_width
            new_height = int(icon_raw.height * scale)

        icon_scaled = icon_raw.resize((new_width, new_height), Image.Resampling.LANCZOS)
        icon_processed = apply_fancy_style(icon_scaled, size=(new_width, new_height), radius=max(8, new_height // 12), border_width=2)

        processed_width = new_width + 4
        processed_height = new_height + 4

        icon_x = x + (col_width - processed_width) // 2
        icon_y = y + 5

        base.paste(icon_processed, (icon_x, icon_y), icon_processed)

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
    """Generate hero meta image for external use (e.g., digest)"""
    logger.info("get_hero_meta_image called - starting generation")
    try:
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota, using static fallback banner")
            return get_static_fallback_banner()
        banner = await create_infographic(data)
        if banner:
            return banner
        logger.warning("create_infographic returned None, using static fallback banner")
        return get_static_fallback_banner()
    except Exception as e:
        logger.warning(f"Failed to generate hero meta image: {e!r}, using static fallback banner")
        return get_static_fallback_banner()


def get_static_fallback_banner():
    """Создаёт простой статичный баннер когда API недоступен"""
    logger.info("Generating static fallback banner")
    try:
        base = Image.new("RGBA", (1200, 200), (25, 25, 35, 255))
        draw = ImageDraw.Draw(base)

        from datetime import datetime, timezone, timedelta
        MSK = timezone(timedelta(hours=3))
        now_msk = datetime.now(MSK)
        date_text = now_msk.strftime("%d.%m.%Y %H:%M")

        try:
            font = ImageFont.truetype(FONT_PATH, 32)
        except:
            font = ImageFont.load_default()

        draw.text((20, 20), "Dota 2 Hero Meta", fill=(255, 215, 0), font=font)
        draw.text((20, 70), f"Updated: {date_text}", fill=(200, 200, 200), font=font)
        draw.text((20, 120), "API unavailable - using cached data", fill=(150, 150, 150), font=font)

        buf = io.BytesIO()
        base.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Failed to create static fallback banner: {e!r}")
        return None


def setup_hero_meta_job(application: Application):
    """Настройка планировщика для еженедельного обновления мета-героев"""
    chat_id = os.getenv('HERO_META_CHAT_ID')
    if chat_id:
        try:
            application.bot_data['hero_meta_chat_id'] = int(chat_id)
            logger.info(f"Hero meta chat ID set to: {chat_id}")
        except ValueError:
            logger.warning(f"Invalid HERO_META_CHAT_ID: {chat_id}")
    else:
        logger.warning("HERO_META_CHAT_ID not set in environment variables")
    logger.info("Hero meta setup completed")
