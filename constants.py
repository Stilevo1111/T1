"""
Global constants for the fissure bot.
Extracted from main.py without changing any behavior.
"""

__all__ = [
    # Cooldown
    "COOLDOWN",
    # Banners
    "COOLDOWN_BANNER_URL",
    "PROFILE_BANNER_URL",
    "TOP_BANNER_URL",
    "TOPMMR_BANNER_URL",
    "LINK_BANNER_URL",
    "SETDIGEST_BANNER_URL",
    "ZEUS_BANNER_URL",
    # Timeouts / delays
    "DICE_ANIMATION_DELAY",
    "USER_PROCESSING_TTL",
    "BOT_CAN_DELETE_TTL",
    "JOB_COOLDOWN",
    "WEEKLY_JOB_COOLDOWN",
    # Weekend bonus
    "WEEKEND_BONUS_MULTIPLIERS",
    # Default chances (legacy - some also in stats.py)
    "MULTICAST_DEFAULT_CHANCE",
    "ZEUS_DEFAULT_CHANCE",
    # Digest headers/footers
    "MORNING_DIGEST_HEADER",
    "MORNING_DIGEST_FOOTER",
    "DOTA_DIGEST_HEADER",
    "DOTA_DIGEST_FOOTER",
    # Zeus
    "ZEUS_TEXTS",
    # Welcome
    "WELCOME_PHRASES",
]

# Cooldown for fissure rolls (24 hours)
COOLDOWN = 86400

# Banner URLs
COOLDOWN_BANNER_URL = "https://i.ibb.co/FkzCZxNG/m-Yqbu.jpg"
PROFILE_BANNER_URL = "https://i.ibb.co/n8g8yQYt/dasdsadasdsadasdsad.png"
TOP_BANNER_URL = "https://i.ibb.co/1fbJD2hb/l-Ij20.jpg"
TOPMMR_BANNER_URL = "https://i.ibb.co/CsbCfzTz/Tv-Sd2.jpg"
LINK_BANNER_URL = "https://i.ibb.co/0jdSyXWx/MZXz-H.jpg"
SETDIGEST_BANNER_URL = "https://i.ibb.co/LXsGsfxZ/213.png"
ZEUS_BANNER_URL = "https://i.ibb.co/0jg01gWW/Gemini-Generated-Image-wyz68gwyz68gwyz6-1.png"

# Timeouts and delays
DICE_ANIMATION_DELAY = 1.0
USER_PROCESSING_TTL = 30          # seconds
BOT_CAN_DELETE_TTL = 3600         # 1 hour
JOB_COOLDOWN = 30                 # seconds between job runs
WEEKLY_JOB_COOLDOWN = 60          # seconds between weekly jobs

# Weekend bonus
WEEKEND_BONUS_MULTIPLIERS = [1.5, 2, 2.5]

# Default event chances (can be overridden in DB)
MULTICAST_DEFAULT_CHANCE = 0.15
ZEUS_DEFAULT_CHANCE = 0.05

# Texts
MORNING_DIGEST_HEADER = "рџЊ…Р¤РРЎРЎРЈР Рђ Р”РђР™Р”Р–Р•РЎРў"
MORNING_DIGEST_FOOTER = "рџ”є = СЂРѕСЃС‚ РїРѕР·РёС†РёР№ РІ С‚РѕРїРµ\nрџ”» = С‚РѕРї РїР°РґРµРЅРёРµ\nрџЌЂ = С‚РµРєСѓС‰РёР№ СЃС‚СЂРёРє РїРѕР±РµРґ"
DOTA_DIGEST_HEADER = "рџЋ® DOTA Р”РђР™Р”Р–Р•РЎРў рџ“Љ"
DOTA_DIGEST_FOOTER = "рџ”є = Р»СѓС‡С€РёР№ РІРёРЅСЂРµР№С‚ Р·Р° РЅРµРґРµР»СЋ\nрџ”» = С…СѓРґС€РёР№ РІРёРЅСЂРµР№С‚ Р·Р° РЅРµРґРµР»СЋ\nрџ”ё = С‚РµРєСѓС‰РёР№ СЃС‚СЂРёРє РїРѕР±РµРґ"

# Zeus texts (moved here for centralization)
ZEUS_TEXTS = [
    "вљЎ Zeus <i>В«РќРµР±РµСЃР° СЂР°СЃСЃРІРёСЂРµРїРµР»Рё!В»</i>",
    "вљЎ Zeus <i>В«Р’С‹ С‡СѓРІСЃС‚РІРѕРІР°Р»Рё СЌС‚Рѕ?В»</i>",
    "вљЎ Zeus <i>В«РќРёС‡С‚Рѕ РЅРµ СѓРєСЂРѕРµС‚СЃСЏ РѕС‚ РјРѕРµРіРѕ РіРЅРµРІР°!В»</i>",
    "вљЎ Zeus <i>В«РЇ вЂ” РјРѕР»РЅРёСЏ, С‡С‚Рѕ СЂР°Р·СЂС‹РІР°РµС‚ РЅРµР±РµСЃР°!В»</i>",
    "вљЎ Zeus <i>В«Р“СЂРѕРј Рё РјРѕР»РЅРёСЏ! Р’СЃС‘ РєРѕРЅС‡РµРЅРѕ!В»</i>",
]

# Welcome phrases for new members
WELCOME_PHRASES = [
    "РџСЂРёСЃРѕРµРґРёРЅРёР»СЃСЏ! РџР°РґР¶ РѕР±Р»РёР·РЅСѓР»СЃСЏ РЅР° С‚РµР±СЏ, СЃРІРµР¶РµРµ РјСЏСЃРѕрџЌ–",
    "Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ! РЎРІРµРЅ С…Р»РѕРїРЅСѓР» С‚РµР±СЏ РїРѕ РїР»РµС‡Сѓрџ‘Џ",
    "РќРµ Р·РµРІР°Р№! РЎР»Р°СЂРє С€РµРїС‡РµС‚ С‚РµР±Рµ РЅР° СѓС…Рѕрџ¤«",
    "Р—Р°С…РѕРґРё! Р‘СЂСѓРґР° СЂР°СЃРєРёРЅСѓР»Р° СЃРµС‚СЊ РґР»СЏ С‚РµР±СЏрџ•ёпёЏ",
    "РћС‚РєСЂРѕР№ СЂСѓРЅРґСѓРє! Р”Р¶Р°РіРµСЂРЅР°СѓС‚ РґР°Р» С‚РµР±Рµ РєР»РёРЅРѕРєвљ”пёЏ",
    "РџСЂРёРІРµС‚! Zeus СЃРІРµСЂРєРЅСѓР» РјРѕР»РЅРёРµР№вљЎ",
    "РџРѕРіРЅР°Р»Рё! Spirit Breaker С‚РµР±СЏ РїСЂРѕРєР°С‚РёС‚рџљ•",
    "Р—РґР°СЂРѕРІР°! Tusk РґР°Р» С‚РµР±Рµ РІ РїР»РµС‡Рѕ РєСѓР»Р°С‡РёС‰РµРјрџђ§",
    "РћР№, Р° С‚С‹ РєС‚Рѕ? Axe РїРѕС‡РµСЃР°Р» С‚РµР±Рµ Р·Р°С‚С‹Р»РѕРє СЃРµРєРёСЂРѕР№рџЄ“",
    "РћР№, Р° С‚С‹ РєС‚Рѕ? Morphling СѓРјС‹Р» С‚РµР±Рµ Р»РёС†Рѕрџ’§",
    "РќРµ Р·РµРІР°Р№! Phantom Assassin С…РѕС‡РµС‚ РїРµСЂРµСЃС‡РёС‚Р°С‚СЊ С‚РІРѕРё СЂРµР±СЂР°рџ’Ђ",
    "Р—РґР°СЂРѕРІР°! Slardar Р±СЂС‹Р·РЅСѓР» СЃР»СЋРЅРѕР№рџђџ",
    "Р§РµРіРѕ СѓСЃС‚Р°РІРёР»СЃСЏ? Clinkz РЅР°С‚СЏРЅСѓР» С‚РµР±Рµ С‚РµС‚РёРІСѓрџЏ№",
    "РџСЂРёРІРµС‚! Faceless Void РѕСЃС‚Р°РЅРѕРІРёР» РІСЂРµРјСЏ РЅР° СЃРµРєСѓРЅРґСѓрџ•°пёЏ",
    "Р‘СѓРґСЊ РєР°Рє РґРѕРјР°! Wisp Р·Р°СЃРІРµС‚РёР»СЃСЏ Сѓ С‚РµР±СЏ Р·Р° СЃРїРёРЅРѕР№рџ’«",
    "РќРµ Р·РµРІР°Р№! Techies РўСЂРё, РґРІРµ, РѕРґРЅР° вЂ” СѓР»С‹Р±РЅРёСЃСЊрџ§Ё",
    "Р§РµРіРѕ РІСЃС‚Р°Р»? Primal Beast С‚РѕРїРЅСѓР» вЂ” РїРѕР» С‚СЂРµСЃРЅСѓР»рџ¦Ќ",
    "РЎР»Р°РґРєРёР№! Queen of Pain СѓСЃР»С‹С€Р°Р»Р° С‚РІРѕР№ РіРѕР»РѕСЃрџ‘‘",
]
