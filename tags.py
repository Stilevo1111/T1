import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

TAG_TYPES = {
    "weekly_mvp": "MVP недели",
    "weekly_top2": "Топ-2 MMR",
    "weekly_top3": "Топ-3 MMR",
    "fissure_master": "Мастер фиссур",
    "admin_custom": "Админ",
}

TAG_DISPLAY = {
    "weekly_mvp": "🏆 MVP недели",
    "weekly_top2": "🥈 Топ-2 MMR",
    "weekly_top3": "🥉 Топ-3 MMR",
    "fissure_master": "🍆 Мастер фиссур",
    "admin_custom": "👑 Админ",
}

TAG_PRIORITY = {
    "weekly_mvp": 100,
    "weekly_top2": 90,
    "weekly_top3": 80,
    "fissure_master": 70,
    "admin_custom": 50,
}


def get_user_tags(telegram_id: int) -> list:
    from database import get_user
    user = get_user(telegram_id)
    if not user:
        return []
    raw = user.get("user_tags")
    if not raw:
        return []
    if isinstance(raw, list):
        return [t for t in raw if t in TAG_TYPES]
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [t for t in data if t in TAG_TYPES]
    except Exception:
        pass
    return []


def _save_user_tags(telegram_id: int, tags: list) -> None:
    from database import update_user_field
    payload = json.dumps(tags, ensure_ascii=False)
    update_user_field(telegram_id, "user_tags", payload)


async def _get_chat_member_status(bot, chat_id: int, user_id: int) -> Optional[str]:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status
    except Exception as e:
        logger.debug(f"tag_manager: get_chat_member failed for {user_id}: {e}")
        return None


async def _set_member_tag(bot, chat_id: int, user_id: int, tag: str) -> bool:
    try:
        return await bot.do_api_request(
            endpoint="setChatMemberTag",
            api_kwargs={"chat_id": chat_id, "user_id": user_id, "tag": tag},
            return_type=bool,
        )
    except Exception as e:
        logger.warning(f"tag_manager: setChatMemberTag failed for {user_id}: {e}")
        return False


async def _set_admin_custom_title(bot, chat_id: int, user_id: int, title: str) -> bool:
    try:
        return await bot.set_chat_administrator_custom_title(
            chat_id=chat_id,
            user_id=user_id,
            custom_title=title,
        )
    except Exception as e:
        logger.warning(f"tag_manager: set_chat_administrator_custom_title failed for {user_id}: {e}")
        return False


async def _apply_best_tag(bot, telegram_id: int, chat_id: int) -> None:
    best = get_best_tag(telegram_id)
    title = TAG_TYPES.get(best, "") if best else ""

    status = await _get_chat_member_status(bot, chat_id, telegram_id)
    if status == "member" or status == "restricted":
        await _set_member_tag(bot, chat_id, telegram_id, title)
    elif status in ("administrator", "creator"):
        await _set_admin_custom_title(bot, chat_id, telegram_id, title)
    else:
        logger.debug(f"tag_manager: user {telegram_id} status={status}, skipping tag apply")


async def add_user_tag(telegram_id: int, tag_type: str, bot=None, chat_id: Optional[int] = None) -> bool:
    if tag_type not in TAG_TYPES:
        return False
    current = get_user_tags(telegram_id)
    if tag_type in current:
        if bot and chat_id:
            await _apply_best_tag(bot, telegram_id, chat_id)
        return True
    current.append(tag_type)
    _save_user_tags(telegram_id, current)
    logger.info(f"tag_manager: added tag {tag_type} to user {telegram_id}")
    if bot and chat_id:
        await _apply_best_tag(bot, telegram_id, chat_id)
    return True


async def remove_user_tag(telegram_id: int, tag_type: str, bot=None, chat_id: Optional[int] = None) -> bool:
    current = get_user_tags(telegram_id)
    if tag_type not in current:
        return False
    current = [t for t in current if t != tag_type]
    _save_user_tags(telegram_id, current)
    logger.info(f"tag_manager: removed tag {tag_type} from user {telegram_id}")
    if bot and chat_id:
        await _apply_best_tag(bot, telegram_id, chat_id)
    return True


def get_best_tag(telegram_id: int) -> Optional[str]:
    tags = get_user_tags(telegram_id)
    if not tags:
        return None
    best = None
    best_priority = -1
    for tag in tags:
        priority = TAG_PRIORITY.get(tag, 0)
        if priority > best_priority:
            best_priority = priority
            best = tag
    return best


async def refresh_user_tag(bot, telegram_id: int, chat_id: int) -> None:
    await _apply_best_tag(bot, telegram_id, chat_id)


async def revoke_all_tags(bot, telegram_id: int, chat_id: int) -> None:
    _save_user_tags(telegram_id, [])
    await _apply_best_tag(bot, telegram_id, chat_id)


def format_user_tags(telegram_id: int) -> str:
    tags = get_user_tags(telegram_id)
    if not tags:
        return ""
    lines = []
    for tag in tags:
        label = TAG_DISPLAY.get(tag, TAG_TYPES.get(tag, tag))
        lines.append(f"• {label}")
    return "\n".join(lines)


async def get_telegram_title(bot, telegram_id: int, chat_id: int) -> str:
    best = get_best_tag(telegram_id)
    title = TAG_TYPES.get(best, "") if best else ""
    await _apply_best_tag(bot, telegram_id, chat_id)
    return title


async def ensure_fissure_master_tag(telegram_id: int, chat_id: int, bot) -> None:
    from database import get_fissure_top
    top_users = get_fissure_top(1)
    if top_users and top_users[0].get('telegram_id') == telegram_id:
        logger.info(f"tag_manager: ensure_fissure_master_tag: user {telegram_id} is top-1, ensuring tag")
        await add_user_tag(telegram_id, 'fissure_master', bot=bot, chat_id=chat_id)
    else:
        logger.debug(f"tag_manager: ensure_fissure_master_tag: user {telegram_id} is not top-1, removing tag")
        await remove_user_tag(telegram_id, 'fissure_master', bot=bot, chat_id=chat_id)


async def refresh_fissure_master_tag(bot, chat_id: int) -> None:
    """Independent tag refresh: compare current top-1 with stored winner and swap tag if needed."""
    from database import get_fissure_top, get_config, set_config
    try:
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            return
        chat_id = int(digest_chat_id)
    except Exception as e:
        logger.debug(f"tag_manager: refresh_fissure_master_tag: invalid digest_chat_id: {e}")
        return

    top_users = get_fissure_top(1)
    if not top_users:
        return

    current_winner = top_users[0]
    current_winner_tg_id = current_winner.get('telegram_id')
    if not current_winner_tg_id:
        return

    stored_winner_tg_id = get_config('current_fissure_master_telegram_id')
    if str(current_winner_tg_id) == str(stored_winner_tg_id):
        logger.debug(f"tag_manager: refresh_fissure_master_tag: top-1 unchanged ({current_winner_tg_id})")
        return

    if stored_winner_tg_id:
        try:
            await remove_user_tag(int(stored_winner_tg_id), "fissure_master", bot=bot, chat_id=chat_id)
            logger.info(f"tag_manager: refresh_fissure_master_tag: removed tag from old top-1 {stored_winner_tg_id}")
        except Exception as e:
            logger.warning(f"tag_manager: refresh_fissure_master_tag: failed to remove tag from {stored_winner_tg_id}: {e}")

    try:
        await add_user_tag(current_winner_tg_id, "fissure_master", bot=bot, chat_id=chat_id)
        set_config('current_fissure_master_telegram_id', str(current_winner_tg_id))
        winner_name = current_winner.get('steam_nickname') or current_winner.get('username') or str(current_winner_tg_id)
        logger.info(f"tag_manager: refresh_fissure_master_tag: fissure_master -> {winner_name} ({current_winner_tg_id})")
    except Exception as e:
        logger.error(f"tag_manager: refresh_fissure_master_tag: failed to set tag for {current_winner_tg_id}: {e}")
