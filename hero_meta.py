import asyncio
import requests
import io
from PIL import Image, ImageDraw, ImageFont, ImageOps
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, ContextTypes, CommandHandler
import os
import logging

logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
BACKGROUND_PATH = "background_new.png"
FONT_PATH = "C:/Windows/Fonts/arial.ttf"

# Расширенный список ID героев для каждой роли (чтобы точно набралось по 5)
ROLE_MAPPING = {
    "SAFE LANE": [1, 54, 73, 94, 6, 12, 114, 42],
    "MID LANE": [11, 106, 17, 22, 74, 43, 13, 25, 101],
    "OFF LANE": [2, 98, 28, 38, 7, 51, 69, 107, 108],
    "SOFT SUPP": [102, 64, 5, 8, 46, 121, 111, 20, 110],
    "HARD SUPP": [87, 30, 26, 111, 31, 40, 50, 119]
}

def apply_fancy_style(img, size=(160, 90), radius=15, border_width=3):
    """Обрезает, закругляет углы и добавляет золотую обводку СНАРУЖИ"""
    # Сначала создаем изображение с обводкой снаружи
    # Общий размер будет size + 2*border_width с каждой стороны
    outer_size = (size[0] + 2 * border_width, size[1] + 2 * border_width)
    
    # Обрезаем и масштабируем исходное изображение до указанного размера
    img_scaled = ImageOps.fit(img, size, centering=(0.5, 0.5))
    
    # Создаем маску для закругленных углов внутреннего изображения
    mask = Image.new('L', size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle((0, 0) + size, radius=radius, fill=255)
    
    # Создаем выходное изображение с прозрачным фоном
    output = Image.new('RGBA', outer_size, (0, 0, 0, 0))
    
    # Вставляем масштабированное изображение в центр (с учетом обводки)
    output.paste(img_scaled, (border_width, border_width), mask=mask)
    
    # Рисуем обводку вокруг всего изображения
    draw_border = ImageDraw.Draw(output)
    draw_border.rounded_rectangle(
        (0, 0, outer_size[0]-1, outer_size[1]-1),
        radius=radius + border_width,  # Увеличиваем радиус для внешней обводки
        outline=(255, 204, 0), 
        width=border_width
    )
    
    return output

async def get_dota_data():
    """Получение статистики с OpenDota"""
    try:
        response = requests.get("https://api.opendota.com/api/heroStats", timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        return None

def create_infographic(hero_stats):
    """Сборка картинки 5x5 с увеличенными иконками (на 0.5X больше)
    
    Returns:
        bytes: PNG image bytes suitable for embedding in digests
    """
    if not os.path.exists(BACKGROUND_PATH):
        base = Image.new("RGBA", (1200, 800), (25, 25, 35, 255))
        bg_width, bg_height = 1200, 800
    else:
        base = Image.open(BACKGROUND_PATH).convert("RGBA")
        bg_width, bg_height = base.size
    
    draw = ImageDraw.Draw(base)
    
    # Текст патча удалён (больше не нужен)
    # 2. РАСЧЕТ РАЗМЕРОВ - УВЕЛИЧЕНИЕ НА 0.5X
    margin_x = 50
    margin_y = 250
    gap_between_cols = 50
    gap_between_rows = 10
    
    available_width = bg_width - 2 * margin_x
    total_gaps_width = 6 * gap_between_cols
    col_width = (available_width - total_gaps_width) // 5
    
    available_height = bg_height - margin_y - 50
    total_gaps_height = 6 * gap_between_rows
    row_height = (available_height - total_gaps_height) // 5
    
    # УВЕЛИЧЕНИЕ НА 0.5X
    base_icon_height = row_height - 25
    increased_height = int(base_icon_height * 1.5)
    icon_height = min(increased_height, row_height - 5)
    
    start_x = margin_x + gap_between_cols
    start_y = margin_y
    
    # Жирный шрифт для WINRATE
    try:
        font_wr = ImageFont.truetype(FONT_PATH, 18)
        # Пробуем найти жирный вариант
        for bold_name in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
            try:
                font_wr = ImageFont.truetype(bold_name, 18)
                break
            except:
                continue
    except:
        font_wr = ImageFont.load_default()

    for col_idx, (role_name, hero_ids) in enumerate(ROLE_MAPPING.items()):
        role_heroes = [h for h in hero_stats if h['id'] in hero_ids]
        for h in role_heroes:
            pro_win = h.get('pro_win', 0)
            pro_pick = h.get('pro_pick', 0)
            h['wr'] = (pro_win / pro_pick * 100) if pro_pick > 0 else 0
        
        top_5 = sorted(role_heroes, key=lambda x: x['wr'], reverse=True)[:5]

        for row_idx, hero in enumerate(top_5):
            x = start_x + col_idx * (col_width + gap_between_cols)
            y = start_y + row_idx * (row_height + gap_between_rows)
            
            # Оригинальная прямоугольная иконка с увеличением 0.5X
            icon_url = "https://cdn.cloudflare.steamstatic.com" + hero['img']
            try:
                r = requests.get(icon_url, timeout=5)
                icon_raw = Image.open(io.BytesIO(r.content)).convert("RGBA")
                
                # Масштабируем по увеличенной высоте (0.5X больше)
                scale = icon_height / icon_raw.height
                new_width = int(icon_raw.width * scale)
                new_height = icon_height
                
                if new_width > col_width:
                    scale = col_width / icon_raw.width
                    new_width = col_width
                    new_height = int(icon_raw.height * scale)
                
                icon_scaled = icon_raw.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Используем готовую функцию для обводки и закругления
                # Сначала масштабируем иконку
                icon_processed = apply_fancy_style(icon_scaled, size=(new_width, new_height), radius=max(8, new_height // 12), border_width=2)
                
                # Размер обработанной иконки с внешней обводкой
                processed_width = new_width + 4  # 2*border_width где border_width=2
                processed_height = new_height + 4
                
                # Позиция по центру в колонке
                icon_x = x + (col_width - processed_width) // 2
                icon_y = y + 5
                base.paste(icon_processed, (icon_x, icon_y), icon_processed)
                
                # ТЕКСТ WINRATE ВНУТРИ ИКОНКИ - В ЦЕНТРЕ ВНИЗУ (БЕЗ ЧЕРНОЙ ПОДКЛАДКИ!)
                wr_value = round(hero['wr'])
                wr_text = f"{wr_value}%"
                
                # Позиция: в самом низу оригинальной иконки (без обводки), по центру
                icon_center_x = icon_x + processed_width // 2  # Центр обработанной иконки
                icon_bottom_y = icon_y + new_height + 2 - 12   # Низ оригинальной иконки + отступ (new_height + 2*border_width - отступ)
                
                try:
                    # Используем жирный шрифт большего размера (увеличен в 1.5 раза от оригинала 18pt = 27pt)
                    font_large = ImageFont.truetype(FONT_PATH, 27)
                    for bold_name in ['arialbd.ttf', 'Arial-Bold.ttf', 'DejaVuSans-Bold.ttf']:
                        try:
                            font_large = ImageFont.truetype(f"C:/Windows/Fonts/{bold_name}", 27)
                            break
                        except:
                            continue
                except:
                    font_large = ImageFont.load_default()
                
                try:
                    bbox = draw.textbbox((0, 0), wr_text, font=font_large)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    
                    # Центрируем текст
                    text_x = icon_center_x - text_width // 2
                    text_y = icon_bottom_y - text_height
                    
                    # Текст - ЖИРНЫЙ, БОЛЬШОЙ, БЕЛЫЙ, БЕЗ ЧЕРНОЙ ПОДКЛАДКИ!
                    # Добавляем обводку (контур) для лучшей читаемости
                    outline_color = (0, 0, 0)
                    # Рисуем контур вокруг текста (множественные смещения)
                    for dx in [-1, 0, 1]:
                        for dy in [-1, 0, 1]:
                            if dx != 0 or dy != 0:
                                draw.text((text_x + dx, text_y + dy), wr_text, fill=outline_color, font=font_large)
                    # Основной текст поверх
                    draw.text((text_x, text_y), wr_text, fill=(255, 255, 255), font=font_large)
                    
                except Exception:
                    # Если не получилось - просто жирный текст
                    draw.text((icon_center_x - 20, icon_bottom_y - 20),
                             wr_text, fill=(255, 255, 255), font=font_large)
                    # Если не получилось - просто жирный текст
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

async def weekly_hero_meta(context: ContextTypes.DEFAULT_TYPE):
    """Основная задача: собрать, нарисовать, отправить и закрепить еженедельную мету"""
    try:
        logger.info("Starting weekly hero meta update")
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota")
            return None
        image_buf = create_infographic(data)
        
        # Also save to file for external use (e.g., digest)
        try:
            with open("hero_meta_header.png", "wb") as f:
                f.write(image_buf)
            logger.info("Saved hero_meta_header.png for external use")
        except Exception as e:
            logger.warning(f"Could not save hero_meta_header.png: {e}")
        
        chat_id = context.bot_data.get('hero_meta_chat_id')
        if not chat_id:
            chat_id = os.getenv('HERO_META_CHAT_ID')
        if not chat_id:
            logger.warning("Hero meta chat ID not configured")
            return
        my_channel = context.bot_data.get('hero_meta_channel')
        if not my_channel:
            my_channel = os.getenv('HERO_META_CHANNEL', 'https://t.me/Seredin999')
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔵 ПОДПИСАТЬСЯ", url=my_channel)]
        ])
        photo = InputFile(image_buf, filename="meta_update.png")
        msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption="📊 **ОБНОВЛЕНИЕ МЕТЫ**\nТоп-5 героев для каждой позиции уже в закрепе\\.",
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
        )
        await context.bot.pin_chat_message(chat_id, msg.message_id)
        logger.info(f"Weekly hero meta posted and pinned in chat {chat_id}")
    except Exception as e:
        logger.error(f"Error in weekly_hero_meta: {e}", exc_info=True)


async def meta_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /meta command for immediate posting and return image bytes"""
    try:
        logger.info("Starting immediate hero meta update via /meta command")
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota")
            if update.message:
                await update.message.reply_text("❌ Ошибка получения данных с OpenDota")
            return None
            
        image_buf = create_infographic(data)
        
        # Save for external use
        try:
            with open("hero_meta_header.png", "wb") as f:
                f.write(image_buf)
            logger.info("Saved hero_meta_header.png for external use")
        except Exception as e:
            logger.warning(f"Could not save hero_meta_header.png: {e}")
        
        # If called from chat, send the photo
        if update.message:
            chat_id = update.effective_chat.id
            photo = InputFile(image_buf, filename="meta_update.png")
            msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption="📊 **ОБНОВЛЕНИЕ МЕТЫ**\nТоп-5 героев для каждой позиции\\.",
                parse_mode="MarkdownV2"
            )
            logger.info(f"Hero meta posted immediately in chat {chat_id}")
        
        return image_buf
            
        image_buf = create_infographic(data)
        chat_id = update.effective_chat.id
        
        # Send the image
        photo = InputFile(image_buf, filename="meta_update.png")
        msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption="📊 **ОБНОВЛЕНИЕ МЕТЫ**\nТоп-5 героев для каждой позиции (запрошено через /meta)\\.",
            parse_mode="MarkdownV2"
        )
        logger.info(f"Hero meta posted immediately in chat {chat_id}")
    except Exception as e:
        logger.error(f"Error in meta_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при создании обновления меты")

def get_hero_meta_image():
    """Generate hero meta image for external use (e.g., digests).
    
    Returns:
        bytes: PNG image bytes that can be embedded as a header,
               or None if generation failed.
    """
    async def _generate():
        data = await get_dota_data()
        if not data:
            logger.error("No data from OpenDota")
            return None
        return create_infographic(data)
    
    import asyncio
    return asyncio.run(_generate())


def setup_hero_meta_job(application: Application):
    """Настройка планировщика для еженедельного обновления меты героев"""
    chat_id = os.getenv('HERO_META_CHAT_ID')
    if chat_id:
        try:
            application.bot_data['hero_meta_chat_id'] = int(chat_id)
            logger.info(f"Hero meta chat ID set to: {chat_id}")
        except ValueError:
            logger.warning(f"Invalid HERO_META_CHAT_ID: {chat_id}")
    else:
        logger.warning("HERO_META_CHAT_ID not set in environment variables")
    from datetime import time
    # Run weekly on Fridays (weekday 4 where Monday=0, Sunday=6)
    application.job_queue.run_daily(
        weekly_hero_meta,
        time=time(hour=10, minute=0),
        days=(4,),  # Only Friday
        name="weekly_hero_meta"
    )
    # Add command handler for immediate posting
    application.add_handler(CommandHandler("meta", meta_command))
    logger.info("Hero meta job scheduled for Fridays at 10:00 and /meta command enabled")