"""
Команда /party — подбор игроков по близости MMR.

Алгоритм:
  1. Находим игроков с MMR выше пользователя (по наименьшей разнице), до PARTY_MAX_ABOVE шт.
  2. Выводим самого пользователя в центре списка (позиция 5, помечается 🔍).
  3. Находим игроков с MMR ниже пользователя (по наименьшей разнице), до PARTY_MAX_BELOW шт.

Итого: до (4 + 1 + 3) = 8 игроков.

Формат вывода:
  1️⃣Nick
  └📈5450•🔥67%
  2️⃣Nick
  └📈5400•🔥65%
  🔍MyNick
  └📈5320•Нет игр за неделю
  5️⃣Nick
  └📈5300•🔥63%
  6️⃣Nick
  └📈5260•🔥59%
  7️⃣Nick
  └📈5220•🔥57%
  8️⃣Nick
  └📈5180•🔥55%

Кнопки: InlineKeyboard с callback_data (не inline-кнопки).
  При нажатии на цифру в чат отправляется @username игрока.

Важно: inline-режим бота НЕ требуется.
"""

from __future__ import annotations

import logging
import os

from bot_utils import clickable_name, make_clickable
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

PARTY_MAX_ABOVE = 4
PARTY_MAX_BELOW = 4


def get_week_wr(user: dict) -> int:
    games = user.get("week_games") or 0
    if games == 0:
        return 0
    wins = user.get("week_wins") or 0
    return round((wins / games) * 100) if games > 0 else 0


def build_callback_keyboard(players: list) -> InlineKeyboardMarkup:
    buttons = []
    for i, p in enumerate(players, 1):
        # Skip position 5 (your position - 🔍)
        if i == 5:
            continue
        
        telegram_id = p.get("telegram_id")
        username = p.get("username") or ""
        if username and username.startswith("@"):
            username = username[1:]
        if not username or username == "—":
            username = f"tg{telegram_id}" if telegram_id else "bot"
        
        # Display numbering with emojis: 1-4, 5-8
        if i <= 4:
            num = i
        elif i > 5:
            num = i - 1  # 6→5, 7→6, 8→7, 9→8
        else:
            num = i
        
        btn_text = f"{num}️⃣"
        btn = InlineKeyboardButton(btn_text, callback_data=f"party_user:{username}")
        buttons.append(btn)
    
    # Layout: 4 buttons per row
    rows = []
    for i in range(0, len(buttons), 4):
        rows.append(buttons[i:i+4])
    
    return InlineKeyboardMarkup(rows)


def build_inline_keyboard(players: list) -> InlineKeyboardMarkup:
    buttons = []
    for i, p in enumerate(players, 1):
        telegram_id = p.get("telegram_id")
        username = p.get("username") or ""
        if username and username.startswith("@"):
            username = username[1:]
        if username and " " in username:
            username = username.split()[0]
        if not username or username == "—":
            username = f"tg{telegram_id}" if telegram_id else "bot"
        btn = InlineKeyboardButton(str(i), switch_inline_query_current_chat=f"@{username}")
        buttons.append(btn)
    return InlineKeyboardMarkup([buttons[:4], buttons[4:8]])


async def party_for_user(chat_id, chat_type, requester, context):
    if not requester.get("steam_id"):
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Привяжи Steam через /link, чтобы подобрать игроков.",
        )
        return

    try:
        loading = await context.bot.send_message(chat_id=chat_id, text="<b>🪝 Ищу игроков...</b>", parse_mode="HTML")

        from database import get_all_users_with_steam
        candidates = get_all_users_with_steam() or []
        candidates = [c for c in candidates if c.get("steam_id") and c.get("telegram_id") != requester.get("telegram_id")]

        req_mmr = float(requester.get("mmr") or 0) if isinstance(requester.get("mmr"), (int, float, str)) else 0
        logger.info(f"party: requester telegram_id={requester.get('telegram_id')} mmr={req_mmr} candidates={len(candidates)}")
        for c in candidates[:10]:
            logger.info(f"party: candidate telegram_id={c.get('telegram_id')} mmr={c.get('mmr')} steam_id={c.get('steam_id')} week_games={c.get('week_games')}")

        # Players above (sorted by MMR difference ascending, take up to 4)
        above = sorted([c for c in candidates if (c.get("mmr") or 0) > req_mmr], key=lambda c: float(c.get("mmr") or 0) - req_mmr)[:4]
        
        # Players below (sorted by MMR difference ascending, take up to 4)
        below = sorted([c for c in candidates if (c.get("mmr") or 0) < req_mmr], key=lambda c: req_mmr - float(c.get("mmr") or 0))[:4]

        players = above + [requester] + below

        if not players:
            players = []

        lines = []
        # Players numbered: 1-4 above, 5=your position (🔍), 6-8 below
        # But display numbering: 1-4, 🔍, then 5-8 for below players
        for idx, p in enumerate(players, 1):
            if idx == 5:
                rank = "🔍"
            elif idx <= 4:
                rank = f"{idx}️⃣"
            else:
                # idx 6,7,8,9 → display as 5,6,7,8 with emoji
                rank = f"{idx - 1}️⃣"
            telegram_id = p.get("telegram_id")
            steam_nick = p.get("steam_nickname") or p.get("username") or None
            steam_id = p.get("steam_id")
            rank_tier = p.get("rank_tier", 0) or 0
            mmr = p.get("mmr") or 0
            has_games = (p.get("week_games") or 0) > 0
            from dota_mmr import rank_to_string
            player_rank = rank_to_string(rank_tier)
            name = f"<b>{clickable_name(steam_nick or '—', telegram_id, steam_id)}</b>"
            if has_games:
                second = f"└ {mmr} • WR {get_week_wr(p)}%"
            else:
                second = f"└ {mmr} • Нет игр за неделю"
            lines.append(f"{rank}{name} - {player_rank}")
            lines.append(second)

        text = "\n".join(lines) if lines else "❌ Не найдено игроков для подбора."

        try:
            await loading.delete()
        except Exception as e:
            logger.debug(f"Could not delete loading message: {e}")

        if players:
            keyboard = build_callback_keyboard(players)
            result_msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=keyboard)
            # Schedule auto-delete after 30 seconds
            try:
                import asyncio
                async def delete_after_delay():
                    await asyncio.sleep(30)
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=result_msg.message_id)
                    except Exception:
                        pass
                asyncio.create_task(delete_after_delay())
            except Exception as e:
                logger.debug(f"Could not schedule auto-delete: {e}")
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in party_for_user: {e}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка подбора. Попробуй позже.")
        except Exception as send_error:
            logger.debug(f"Could not send error message: {send_error}")


async def party_command(update, context):
    logger.info(f"User {update.effective_user.id} called party")

    chat_id = update.message.chat_id
    chat_type = update.message.chat.type

    if chat_type in ("group", "supergroup", "channel"):
        try:
            await update.message.delete()
        except Exception as e:
            logger.debug(f"Could not delete user message: {e}")

    try:
        user_obj = update.effective_user
        from database import get_user
        requester = get_user(user_obj.id, user_obj.username or user_obj.first_name or f"Player{user_obj.id}")
        if not requester:
            requester = {
                "telegram_id": user_obj.id,
                "username": user_obj.username or user_obj.first_name or f"Player{user_obj.id}",
                "steam_id": None,
                "mmr": 0,
                "week_games": 0,
                "week_wins": 0,
            }

        await party_for_user(chat_id, chat_type, requester, context)

    except Exception as e:
        logger.error(f"Error in party_command: {e}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка подбора. Попробуй позже.")
        except Exception as send_error:
            logger.debug(f"Could not send error message: {send_error}")