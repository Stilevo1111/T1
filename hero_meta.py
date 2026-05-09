# hero_meta.py — асинхронная версия с позиционной статистикой, без дублей

import asyncio
import aiohttp
import io
import os
import logging
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, ContextTypes, CommandHandler

logger = logging.getLogger(__name__)

BACKGROUND_PATH = "background_new.png"

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
    except Exception:
        continue

if FONT_PATH is None:
    FONT_PATH = ImageFont.load_default()
    logger.warning("Using default PIL font as no system fonts found")


def apply_fancy_style(img, size=(188, 100), radius=15, border_width=3):
    """Закругление и золотая обводка"""
    outer_size = (size[0] + 2 * border_width, size[1] + 2 * border_width)
    img_scaled = img.resize(size, Image.Resampling.LANCZOS)
    mask = Image.new('L', size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle((0, 0) + size, radius=radius, fill=255)
    output = Image.new('RGBA', outer_size, (0, 0, 0, 0))
    output.paste(img_scaled, (border_width, border_width), mask=mask)
    draw_border = ImageDraw.Draw(output)
    draw_border.rounded_rectangle(
        (0, 0) + outer_size, radius=radius, outline=(255, 215, 0, 255), width=2
    )
    return output


async def fetch_hero_icon(session, icon_path):
    """Асинхронная загрузка иконки героя"""
    if icon_path.startswith('/'):
        icon_url = f"https://cdn.cloudflare.steamstatic.com{icon_path}"
    elif not icon_path.startswith('http'):
        icon_url = f"https://cdn.cloudflare.steamstatic.com/{icon_path}"
    else:
        icon_url = icon_path

    try:
        async with session.get(icon_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            resp.raise_for_status()
            content = await resp.read()
            return Image.open(io.BytesIO(content)).convert("RGBA")
    except Exception as e:
        logger.error(f"Failed to load icon: {e!r}")
        raise


def _parse_position(player_slot):
    """Определяет позицию (1-5) по player_slot.
    OpenDota: Radiant 0-4, Dire 128-132
    Позиция 1=Carry, 2=Mid, 3=Offlane, 4=Soft Support, 5=Hard Support
    """
    if player_slot < 128:
        return player_slot + 1
    else:
        return player_slot - 127


async def get_weekly_hero_stats():
    """Статистика героев из матчей за последние 7 дней"""
    try:
        from datetime import datetime, timedelta

        matches = []
        url = f"https://api.opendota.com/api/matches?date=7&limit=200"
        timeout = aiohttp.ClientTimeout(total=5)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as resp:
                if resp.status == 200:
                    matches = await resp.json()
                    logger.info(f"Fetched {len(matches)} matches")
                else:
                    logger.error(f"Matches API error: HTTP {resp.status}")

        if not matches:
            return await get_fallback_hero_stats()

        # Агрегируем позиционную статистику
        hero_stats = {}

        for match in matches:
            if not match.get('players'):
                continue
            radiant_win = match.get('radiant_win', False)

            for player in match['players']:
                hero_id = player.get('hero_id')
                if not hero_id:
                    continue

                player_slot = player.get('player_slot', 0)
                pos = _parse_position(player_slot)
                if pos < 1 or pos > 5:
                    continue

                if hero_id not in hero_stats:
                    hero_stats[hero_id] = {
                        p: {'picks': 0, 'wins': 0} for p in range(1, 6)
                    }

                hero_stats[hero_id][pos]['picks'] += 1
                is_radiant = player_slot < 128
                if (is_radiant and radiant_win) or (not is_radiant and not radiant_win):
                    hero_stats[hero_id][pos]['wins'] += 1

        # Формируем hero_list с позиционными полями
        hero_list = []
        for hero_id, pos_data in hero_stats.items():
            total_picks = sum(pos_data[p]['picks'] for p in range(1, 6))
            if total_picks >= 10:
                entry = {
                    'id': hero_id,
                    'localized_name': f'Hero {hero_id}',
                    'img': f'/apps/dota2/images/dota_react/heroes/icons/{hero_id}.png',
                    'pro_win': sum(pos_data[p]['wins'] for p in range(1, 6)),
                    'pro_pick': total_picks,
                }
                for p in range(1, 6):
                    entry[f'{p}_pick'] = pos_data[p]['picks']
                    entry[f'{p}_win'] = pos_data[p]['wins']
                hero_list.append(entry)

        logger.info(f"Calculated weekly stats for {len(hero_list)} heroes")
        return hero_list

    except Exception as e:
        logger.error(f"Weekly stats error: {e!r}")
        return await get_fallback_hero_stats()


async def get_fallback_hero_stats():
    """Fallback: heroStats из OpenDota"""
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.opendota.com/api/heroStats", timeout=timeout
            ) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                hero_stats = await resp.json()
                if not hero_stats:
                    raise Exception("Empty")

        hero_list = []
        for hero in hero_stats:
            pro_pick = hero.get('pro_pick', 0)
            if pro_pick < 50:
                continue

            img_raw = hero.get('img', '')
            if img_raw.startswith('http'):
                img_path = urlparse(img_raw).path
            else:
                img_path = img_raw
            if not img_path.startswith('/'):
                img_path = '/' + img_path

            entry = {
                'id': hero['id'],
                'localized_name': hero.get('localized_name', f'Hero {hero["id"]}'),
                'img': img_path,
                'pro_win': hero.get('pro_win', 0),
                'pro_pick': pro_pick,
            }
            for p in range(1, 6):
                pk = f'{p}_pick'
                wk = f'{p}_win'
                entry[pk] = hero.get(pk, 0)
                entry[wk] = hero.get(wk, 0)
            hero_list.append(entry)

        logger.info(f"Fallback: loaded {len(hero_list)} heroes")
        return hero_list

    except Exception as e:
        logger.error(f"Fallback error: {e!r}")
        return None


async def get_dota_data(days=7):
    return await get_weekly_hero_stats()


def _build_grid(hero_stats):
    """
    Строит сетку 5x5: каждый герой на своей ОСНОВНОЙ позиции.
    Основная позиция = та, где максимально picks.
    Без дублей — каждый герой только в одном столбце.
    """
    hero_main_pos = {}
    for hero in hero_stats:
        best_pos = None
        best_picks = 0
        for pos in range(1, 6):
            picks = hero.get(f'{pos}_pick', 0)
            if picks > best_picks:
                best_picks = picks
                best_pos = pos
        if best_pos and best_picks > 0:
            hero_main_pos[hero['id']] = best_pos

    by_position = {1: [], 2: [], 3: [], 4: [], 5: []}
    for hero in hero_stats:
        hid = hero['id']
        if hid not in hero_main_pos:
            continue
        pos = hero_main_pos[hid]
        picks = hero.get(f'{pos}_pick', 0)
        if picks < 1:  # минимум 1 игра на позиции
            continue
        wins = hero.get(f'{pos}_win', 0)
        wr = (wins / picks * 100) if picks > 0 else 0
        by_position[pos].append({
            'id': hid,
            'name': hero.get('localized_name', f'Hero {hid}'),
            'img': hero['img'],
            'wr': wr,
            'picks': picks,
            'wins': wins,
        })

    # Сортируем каждую позицию по винрейту (desc) и берём топ-5
    grid = {}
    for pos in range(1, 6):
        sorted_heroes = sorted(by_position[pos], key=lambda h: -h['wr'])[:5]
        grid[pos] = sorted_heroes

    return grid


async def create_infographic(hero_stats):
    """Баннер 5x5: по 5 героев на каждую позицию. Без дублей, без подписей."""
    logger.info("Starting create_infographic")

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
    text_x = bg_width - (bbox[2] - bbox[0]) - 20
    draw.text((text_x, 20), date_text, fill=(255, 255, 255), font=date_font)

    margin_x = 50
    margin_y = 215
    gap_between_cols = 15

    col_width = (bg_width - 2 * margin_x - 6 * gap_between_cols) // 5
    row_height = (bg_height - margin_y - 10) // 5

    base_icon_height = row_height - 25
    icon_height = min(int(base_icon_height * 1.163), row_height - 5)

    try:
        font_wr = ImageFont.truetype(FONT_PATH, 27)
        for bn in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
            try:
                font_wr = ImageFont.truetype(bn, 20)
                break
            except:
                continue
    except:
        font_wr = ImageFont.load_default()

    # Строим сетку из героев
    grid = _build_grid(hero_stats)

    # Собираем уникальных героев
    all_heroes = []
    seen_ids = set()
    for pos in range(1, 6):
        for hero in grid[pos]:
            if hero['id'] not in seen_ids:
                seen_ids.add(hero['id'])
                all_heroes.append(hero)

    # Асинхронная загрузка иконок
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_hero_icon(session, h['img']) for h in all_heroes]
        icons = {}
        for i, hero in enumerate(all_heroes):
            try:
                icons[hero['id']] = await tasks[i]
            except Exception:
                icons[hero['id']] = None

    # Отрисовка: колонка = позиция, строки = топ героев позиции
    for col_idx in range(5):
        pos = col_idx + 1
        heroes = grid[pos]

        for row_idx, hero in enumerate(heroes[:5]):
            x = margin_x + col_idx * (col_width + gap_between_cols)
            y = margin_y + row_idx * row_height

            icon_raw = icons.get(hero['id'])

            if icon_raw is None:
                draw.rounded_rectangle(
                    [x + 5, y + 5, x + col_width - 5, y + icon_height],
                    radius=10, fill=(80, 80, 80)
                )
                # Серый placeholder
                try:
                    ph_font = ImageFont.truetype(FONT_PATH, 16)
                except:
                    ph_font = ImageFont.load_default()
                draw.text((x + 10, y + icon_height // 2 - 8), "N/A", fill=(120, 120, 120), font=ph_font)
                continue

            # Масштабирование
            scale = icon_height / icon_raw.height
            nw = int(icon_raw.width * scale)
            nh = icon_height
            if nw > col_width:
                scale = col_width / icon_raw.width
                nw = col_width
                nh = int(icon_raw.height * scale)

            icon_scaled = icon_raw.resize((nw, nh), Image.Resampling.LANCZOS)
            icon_proc = apply_fancy_style(icon_scaled, size=(nw, nh),
                                          radius=max(8, nh // 12), border_width=2)

            pw = nw + 4
            icon_x = x + (col_width - pw) // 2
            icon_y = y + 5

            base.paste(icon_proc, (icon_x, icon_y), icon_proc)

            wr_text = f"{round(hero['wr'])}%"

            try:
                font_lg = ImageFont.truetype(FONT_PATH, 28)
                for bn in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
                    try:
                        font_lg = ImageFont.truetype(f"C:/Windows/Fonts/{bn}", 28)
                        break
                    except:
                        continue
            except:
                font_lg = ImageFont.load_default()

            try:
                bb = draw.textbbox((0, 0), wr_text, font=font_lg)
                tw = bb[2] - bb[0]
                th = bb[3] - bb[1]
                tx = icon_x + pw // 2 - tw // 2
                ty = icon_y + nh + 2 - 12 - th
                draw.text((tx, ty), wr_text, fill=(255, 255, 255), font=font_lg)
            except Exception:
                draw.text((icon_x + pw // 2 - 20, icon_y + nh - 30),
                          wr_text, fill=(255, 255, 255), font=font_lg)

    buf = io.BytesIO()
    base.save(buf, format='PNG')
    return buf.getvalue()


async def get_hero_meta_image():
    """Generate hero meta image"""
    logger.info("get_hero_meta_image called")
    try:
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota")
            return get_static_fallback_banner()
        banner = await create_infographic(data)
        if banner:
            return banner
        return get_static_fallback_banner()
    except Exception as e:
        logger.warning(f"Hero meta generation failed: {e!r}")
        return get_static_fallback_banner()


def get_static_fallback_banner():
    """Статичный баннер когда API недоступен"""
    logger.info("Generating static fallback banner")
    try:
        base = Image.new("RGBA", (1200, 200), (25, 25, 35, 255))
        draw = ImageDraw.Draw(base)
        from datetime import datetime, timezone, timedelta
        MSK = timezone(timedelta(hours=3))
        date_text = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
        try:
            font = ImageFont.truetype(FONT_PATH, 32)
        except:
            font = ImageFont.load_default()
        draw.text((20, 20), "Dota 2 Hero Meta", fill=(255, 215, 0), font=font)
        draw.text((20, 70), f"Updated: {date_text}", fill=(200, 200, 200), font=font)
        draw.text((20, 120), "API unavailable", fill=(150, 150, 150), font=font)
        buf = io.BytesIO()
        base.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Static banner error: {e!r}")
        return None


def setup_hero_meta_job(application: Application):
    chat_id = os.getenv('HERO_META_CHAT_ID')
    if chat_id:
        try:
            application.bot_data['hero_meta_chat_id'] = int(chat_id)
            logger.info(f"Hero meta chat ID set to: {chat_id}")
        except ValueError:
            logger.warning(f"Invalid HERO_META_CHAT_ID: {chat_id}")
    else:
        logger.warning("HERO_META_CHAT_ID not set")
    logger.info("Hero meta setup completed")