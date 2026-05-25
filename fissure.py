# -*- coding: utf-8 -*-
"""
Fissure-specific logic extracted from main.py.
This module contains the core fissure roll handling and related helpers.
All extractions are done without changing any bot behavior or visuals.
"""

import asyncio
import random
import logging
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import ContextTypes

# Imports from other modules (will be adjusted as we extract more)
# The following are prepared for the full fissure() implementation (do not remove during incremental extraction)
from bot_utils import (
    delete_last_bot_message,
    set_last_bot_message,
    schedule_delete,
    main_menu,
)
from rolls import (
    calculate_fissure_roll,
    apply_fissure_protection,
    calculate_new_fissure,
    check_multicast,
    MULTICAST_TEXTS,
)
from stats import get_event_chances
from database import get_user, update_fissure, update_last_message_id, zeus_strike
from constants import (
    COOLDOWN,
    ZEUS_BANNER_URL,
    WEEKEND_BONUS_MULTIPLIERS,
    ZEUS_TEXTS,
)

logger = logging.getLogger(__name__)


async def send_fissure_result(
    bot,
    chat_id,
    user_id,
    text,
    banner_url=None,
    reply_markup=None,
    delete_after=30,
):
    """Helper to send fissure result (photo or text) and track it for later deletion."""
    if banner_url:
        result_msg = await bot.send_photo(
            chat_id=chat_id,
            photo=banner_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    else:
        result_msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    set_last_bot_message(chat_id, user_id, result_msg.message_id)
    schedule_delete(bot, chat_id, result_msg.message_id, delete_after, None)  # job_queue passed from caller if needed
    update_last_message_id(user_id, result_msg.message_id)
    return result_msg


# The main fissure handler (to be moved fully in future steps)
# For now, we keep the skeleton here for future extraction.
# All changes in this file must preserve exact original behavior from main.py.
async def fissure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Main handler for fissure rolls.
    This is a large function; we will gradually extract helpers from it
    without changing any behavior or user-facing output.
    """
    # The full implementation is still in main.py for safety during incremental extraction.
    # In future steps we will move the body here.
    # IMPORTANT: Never change logic or messages in this file until the full migration is complete and tested.
    raise NotImplementedError("Full implementation still in main.py during incremental extraction")
