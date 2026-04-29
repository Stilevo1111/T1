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
ROLE_MAPPING = {

    "SAFE LANE": [1, 8, 54, 73, 94, 6, 12, 114, 42],

    "MID LANE": [11, 106, 17, 22, 74, 43, 13, 25, 46, 113],

    "OFF LANE": [2, 98, 28, 38, 7, 51, 69, 107, 108, 110],

    "SOFT SUPP": [102, 64, 5, 101, 121, 20, 112],

    "HARD SUPP": [87, 30, 26, 111, 31, 40, 50, 119]

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

async def get_dota_data():
    """╨Я╨╛╨╗╤Г╤З╨╡╨╜╨╕╨╡ ╤Б╤В╨░╤В╨╕╤Б╤В╨╕╨║╨╕ ╤Б OpenDota"""
    try:
        response = requests.get("https://api.opendota.com/api/heroStats", timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"╨Ю╤И╨╕╨▒╨║╨░ API: {e}")
        return None

def create_infographic(hero_stats):
    """Создайте инфографику 5x5 с лучшими героями по ролям (на 0.5X больше)

    Returns:
        bytes: PNG image bytes suitable for embedding in digests
    """
    logger.info("Starting create_infographic generation")
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
            
            # ╨Ю╤А╨╕╨│╨╕╨╜╨░╨╗╤М╨╜╨░╤П ╨┐╤А╤П╨╝╨╛╤Г╨│╨╛╨╗╤М╨╜╨░╤П ╨╕╨║╨╛╨╜╨║╨░ ╤Б ╤Г╨▓╨╡╨╗╨╕╤З╨╡╨╜╨╕╨╡╨╝ 0.5X
            icon_url = "https://cdn.cloudflare.steamstatic.com" + hero['img']
            try:
                r = requests.get(icon_url, timeout=5)
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

async def weekly_hero_meta(context: ContextTypes.DEFAULT_TYPE):
    """╨Ю╤Б╨╜╨╛╨▓╨╜╨░╤П ╨╖╨░╨┤╨░╤З╨░: ╤Б╨╛╨▒╤А╨░╤В╤М, ╨╜╨░╤А╨╕╤Б╨╛╨▓╨░╤В╤М, ╨╛╤В╨┐╤А╨░╨▓╨╕╤В╤М ╨╕ ╨╖╨░╨║╤А╨╡╨┐╨╕╤В╤М ╨╡╨╢╨╡╨╜╨╡╨┤╨╡╨╗╤М╨╜╤Г╤О ╨╝╨╡╤В╤Г"""
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
            [InlineKeyboardButton(text="ЁЯФ╡ ╨Я╨Ю╨Ф╨Я╨Ш╨б╨Р╨в╨м╨б╨п", url=my_channel)]
        ])
        photo = InputFile(image_buf, filename="meta_update.png")
        msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption="ЁЯУК **╨Ю╨С╨Э╨Ю╨Т╨Ы╨Х╨Э╨Ш╨Х ╨Ь╨Х╨в╨л**\n╨в╨╛╨┐-5 ╨│╨╡╤А╨╛╨╡╨▓ ╨┤╨╗╤П ╨║╨░╨╢╨┤╨╛╨╣ ╨┐╨╛╨╖╨╕╤Ж╨╕╨╕ ╤Г╨╢╨╡ ╨▓ ╨╖╨░╨║╤А╨╡╨┐╨╡\\.",
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
                await update.message.reply_text("тЭМ ╨Ю╤И╨╕╨▒╨║╨░ ╨┐╨╛╨╗╤Г╤З╨╡╨╜╨╕╤П ╨┤╨░╨╜╨╜╤Л╤Е ╤Б OpenDota")
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
                caption="ЁЯУК **╨Ю╨С╨Э╨Ю╨Т╨Ы╨Х╨Э╨Ш╨Х ╨Ь╨Х╨в╨л**\n╨в╨╛╨┐-5 ╨│╨╡╤А╨╛╨╡╨▓ ╨┤╨╗╤П ╨║╨░╨╢╨┤╨╛╨╣ ╨┐╨╛╨╖╨╕╤Ж╨╕╨╕\\.",
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
            caption="ЁЯУК **╨Ю╨С╨Э╨Ю╨Т╨Ы╨Х╨Э╨Ш╨Х ╨Ь╨Х╨в╨л**\n╨в╨╛╨┐-5 ╨│╨╡╤А╨╛╨╡╨▓ ╨┤╨╗╤П ╨║╨░╨╢╨┤╨╛╨╣ ╨┐╨╛╨╖╨╕╤Ж╨╕╨╕ (╨╖╨░╨┐╤А╨╛╤И╨╡╨╜╨╛ ╤З╨╡╤А╨╡╨╖ /meta)\\.",
            parse_mode="MarkdownV2"
        )
        logger.info(f"Hero meta posted immediately in chat {chat_id}")
    except Exception as e:
        logger.error(f"Error in meta_command: {e}", exc_info=True)
        await update.message.reply_text("тЭМ ╨Я╤А╨╛╨╕╨╖╨╛╤И╨╗╨░ ╨╛╤И╨╕╨▒╨║╨░ ╨┐╤А╨╕ ╤Б╨╛╨╖╨┤╨░╨╜╨╕╨╕ ╨╛╨▒╨╜╨╛╨▓╨╗╨╡╨╜╨╕╤П ╨╝╨╡╤В╤Л")

async def generate_hero_meta_banner():
    """Async version to generate hero meta banner.
    
    Can be safely called from within an existing event loop.
    
    Returns:
        bytes: PNG image bytes of the hero meta banner
    """
    data = await get_dota_data()
    if not data:
        logger.error("No data from OpenDota")
        return None
    return create_infographic(data)


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

    # Removed weekly job and /meta command as per requirements

    logger.info("Hero meta setup completed (no weekly job or /meta command)")
