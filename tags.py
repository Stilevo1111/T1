import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

TAG_TYPES = {
    "weekly_mvp": "MVP",
    "weekly_top1": "TOP 1",
    "weekly_top2": "MMR Top-2",
    "weekly_top3": "MMR Top-3",
    "fissure_master": "Fissure Master",
    "F1": "Fissure Gold",
    "F2": "Fissure Silver",
    "F3": "Fissure Bronze",
    "VIP": "VIP",
    "admin_custom": "Administrator",
}

TAG_DISPLAY = {
    "weekly_mvp": "MVP",
    "weekly_top1": "Top-1",
    "weekly_top2": "MMR Top-2",
    "weekly_top3": "MMR Top-3",
    "fissure_master": "Fissure Master",
    "F1": "Fissure Gold",
    "F2": "Fissure Silver",
    "F3": "Fissure Bronze",
    "admin_custom": "Administrator",
    "VIP": "VIP",
}

TAG_PRIORITY = {
    "VIP": 1000,
    "weekly_mvp": 100,
    "weekly_top2": 90,
    "weekly_top3": 80,
    "F1": 78,
    "F2": 76,
    "F3": 74,
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


async def _is_admin(bot, chat_id: int, user_id: int) -> bool:
    """True if the user is an administrator or creator of the chat."""
    status = await _get_chat_member_status(bot, chat_id, user_id)
    return status in ("administrator", "creator")


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


async def refresh_fissure_master_tag(bot, chat_id: int, notify: bool = True) -> None:
    """Independent tag refresh: compare current top-1 with stored winner and swap tag if needed.

    Administrators are skipped entirely — they keep their own admin tag and are
    never granted or stripped of fissure_master, regardless of their fissure rank.
    """
    from database import get_fissure_top, get_config, set_config, get_user
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

    # Skip administrators — they keep their own tag and never get fissure_master.
    if await _is_admin(bot, chat_id, int(current_winner_tg_id)):
        logger.info(f"tag_manager: refresh_fissure_master_tag: top-1 {current_winner_tg_id} is admin, skipping")
        return

    stored_winner_tg_id = get_config('current_fissure_master_telegram_id')
    if str(current_winner_tg_id) == str(stored_winner_tg_id):
        logger.debug(f"tag_manager: refresh_fissure_master_tag: top-1 unchanged ({current_winner_tg_id})")
        return

    # If the previous holder is an admin, don't try to strip the tag from them.
    old_name = ""
    old_fissure = 0
    if stored_winner_tg_id and not await _is_admin(bot, chat_id, int(stored_winner_tg_id)):
        try:
            await remove_user_tag(int(stored_winner_tg_id), "fissure_master", bot=bot, chat_id=chat_id)
            logger.info(f"tag_manager: refresh_fissure_master_tag: removed tag from old top-1 {stored_winner_tg_id}")
        except Exception as e:
            logger.warning(f"tag_manager: refresh_fissure_master_tag: failed to remove tag from {stored_winner_tg_id}: {e}")
        old_winner = get_user(int(stored_winner_tg_id)) if stored_winner_tg_id else None
        if old_winner:
            old_name = old_winner.get('username') or old_winner.get('steam_nickname') or str(stored_winner_tg_id)
            old_fissure = old_winner.get('fissure', 0)
    elif stored_winner_tg_id:
        logger.info(f"tag_manager: refresh_fissure_master_tag: old top-1 {stored_winner_tg_id} is admin, leaving tag alone")

    try:
        await add_user_tag(current_winner_tg_id, "fissure_master", bot=bot, chat_id=chat_id)
        set_config('current_fissure_master_telegram_id', str(current_winner_tg_id))
        winner_name = current_winner.get('username') or current_winner.get('steam_nickname') or str(current_winner_tg_id)
        logger.info(f"tag_manager: refresh_fissure_master_tag: fissure_master -> {winner_name} ({current_winner_tg_id})")

        if notify:
            new_fissure = current_winner.get('fissure', 0)
            if old_name:
                text = (
                    f"👑 <b>Новый Мастер фиссур!</b>\n\n"
                    f"Топ сменился:\n"
                    f"🥇 <b>{winner_name}</b> — <code>{new_fissure:.1f}</code> см\n"
                    f"👤 <b>{old_name}</b> — <code>{old_fissure:.1f}</code> см"
                )
            else:
                text = (
                    f"👑 <b>Новый Мастер фиссур!</b>\n\n"
                    f"🥇 <b>{winner_name}</b> — <code>{new_fissure:.1f}</code> см"
                )
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                logger.info(f"tag_manager: refresh_fissure_master_tag: notification sent to chat {chat_id}")
            except Exception as e:
                logger.warning(f"tag_manager: refresh_fissure_master_tag: failed to send notification: {e}")
    except Exception as e:
        logger.error(f"tag_manager: refresh_fissure_master_tag: failed to set tag for {current_winner_tg_id}: {e}")


async def refresh_fissure_top_tags(bot, chat_id: int, notify: bool = True) -> None:
    """Обновляет теги ТОП 1/2/3 фиссуры при смене мест в топе.

    Золото — 1 место, серебро — 2 место, бронза — 3-15 место.
    Теги забираются у предыдущих держателей при смене состава топа.
    Администраторы пропускаются — они держат свой админ-тег.
    """
    from database import get_fissure_top, get_config, set_config, get_user
    try:
        digest_chat_id = get_config('digest_chat_id')
        if not digest_chat_id:
            return
        chat_id = int(digest_chat_id)
    except Exception as e:
        logger.debug(f"tag_manager: refresh_fissure_top_tags: invalid digest_chat_id: {e}")
        return

    top_users = get_fissure_top(15)
    if not top_users:
        return

    # Текущие держатели тегов
    current_top1 = top_users[0] if len(top_users) > 0 else None
    current_top2 = top_users[1] if len(top_users) > 1 else None
    current_top3 = [u for u in top_users[2:15]] if len(top_users) > 2 else []

    def _tg(u):
        return u.get('telegram_id') if u else None

    def _name(u):
        if not u:
            return ""
        return u.get('username') or u.get('steam_nickname') or str(u.get('telegram_id'))

    async def _is_admin(tg_id):
        if not tg_id:
            return False
        try:
            return await _is_admin(bot, chat_id, int(tg_id))
        except Exception:
            return False

    # --- ТОП 1 (F1) ---
    new_top1_tg = _tg(current_top1)
    stored_top1_tg = get_config('current_F1_telegram_id')

    # Где упал старый топ 1?
    stored_old_top1 = None
    if stored_top1_tg:
        for u in top_users:
            if u and u.get('telegram_id') == int(stored_top1_tg):
                stored_old_top1 = u
                break

    if stored_top1_tg and str(new_top1_tg) != str(stored_top1_tg) and int(stored_top1_tg) != 0:
        # Забираем у старого
        if not await _is_admin(int(stored_top1_tg)):
            try:
                await remove_user_tag(int(stored_top1_tg), "F1", bot=bot, chat_id=chat_id)
                logger.info(f"tag_manager: refresh_fissure_top_tags: removed F1 from {stored_top1_tg}")
            except Exception as e:
                logger.warning(f"tag_manager: refresh_fissure_top_tags: failed to remove F1 from {stored_top1_tg}: {e}")

        # Где упал старый топ 1?
        if stored_old_top1:
            old_pos = None
            for i, u in enumerate(top_users):
                if u and u.get('telegram_id') == int(stored_top1_tg):
                    old_pos = i + 1
                    break
            if old_pos == 2:
                old_tags = get_user_tags(int(stored_top1_tg))
                if "VIP" not in old_tags:
                    await add_user_tag(int(stored_top1_tg), "F2", bot=bot, chat_id=chat_id)
                    logger.info(f"tag_manager: refresh_fissure_top_tags: passed F2 to old top-1 {stored_top1_tg}")
            elif old_pos >= 3:
                old_tags = get_user_tags(int(stored_top1_tg))
                if "VIP" not in old_tags:
                    await add_user_tag(int(stored_top1_tg), "F3", bot=bot, chat_id=chat_id)
                    logger.info(f"tag_manager: refresh_fissure_top_tags: passed F3 to old top-1 {stored_top1_tg}")

    # Выдаём новому
    if new_top1_tg and not await _is_admin(new_top1_tg):
        try:
            await add_user_tag(int(new_top1_tg), "F1", bot=bot, chat_id=chat_id)
            set_config('current_F1_telegram_id', str(new_top1_tg))
            logger.info(f"tag_manager: refresh_fissure_top_tags: F1 -> {_name(current_top1)} ({new_top1_tg})")
        except Exception as e:
            logger.error(f"tag_manager: refresh_fissure_top_tags: failed to set F1 for {new_top1_tg}: {e}")
    else:
        set_config('current_F1_telegram_id', str(new_top1_tg) if new_top1_tg else "")

    # --- ТОП 2 (F2) ---
    new_top2_tg = _tg(current_top2)
    stored_top2_tg = get_config('current_F2_telegram_id')

    # Где упал старый топ 2?
    stored_old_top2 = None
    if stored_top2_tg:
        for u in top_users:
            if u and u.get('telegram_id') == int(stored_top2_tg):
                stored_old_top2 = u
                break

    if stored_top2_tg and str(new_top2_tg) != str(stored_top2_tg) and int(stored_top2_tg) != 0:
        if not await _is_admin(int(stored_top2_tg)):
            try:
                await remove_user_tag(int(stored_top2_tg), "F2", bot=bot, chat_id=chat_id)
                logger.info(f"tag_manager: refresh_fissure_top_tags: removed F2 from {stored_top2_tg}")
            except Exception as e:
                logger.warning(f"tag_manager: refresh_fissure_top_tags: failed to remove F2 from {stored_top2_tg}: {e}")

        # Где упал старый топ 2?
        if stored_old_top2:
            for i, u in enumerate(top_users):
                if u and u.get('telegram_id') == int(stored_top2_tg):
                    if i + 1 >= 3:
                        old_tags = get_user_tags(int(stored_top2_tg))
                        if "VIP" not in old_tags:
                            await add_user_tag(int(stored_top2_tg), "F3", bot=bot, chat_id=chat_id)
                            logger.info(f"tag_manager: refresh_fissure_top_tags: passed F3 to old top-2 {stored_top2_tg}")
                    break

    if new_top2_tg and not await _is_admin(new_top2_tg):
        try:
            await add_user_tag(int(new_top2_tg), "F2", bot=bot, chat_id=chat_id)
            set_config('current_F2_telegram_id', str(new_top2_tg))
            logger.info(f"tag_manager: refresh_fissure_top_tags: F2 -> {_name(current_top2)} ({new_top2_tg})")
        except Exception as e:
            logger.error(f"tag_manager: refresh_fissure_top_tags: failed to set F2 for {new_top2_tg}: {e}")
    else:
        set_config('current_F2_telegram_id', str(new_top2_tg) if new_top2_tg else "")

    # --- ТОП 3 (F3, 3-15 место) ---
    stored_top3_raw = get_config('current_F3_telegram_ids') or ""
    try:
        stored_top3 = [int(x) for x in stored_top3_raw.split(',') if x.strip()]
    except Exception:
        stored_top3 = []
    new_top3 = [_tg(u) for u in current_top3 if _tg(u)]

    # Убираем теги с тех, кого больше нет в топе 3-15
    for old_tg in stored_top3:
        if old_tg not in new_top3 and not await _is_admin(old_tg):
            try:
                await remove_user_tag(int(old_tg), "F3", bot=bot, chat_id=chat_id)
                logger.info(f"tag_manager: refresh_fissure_top_tags: removed F3 from {old_tg}")
            except Exception as e:
                logger.warning(f"tag_manager: refresh_fissure_top_tags: failed to remove F3 from {old_tg}: {e}")

    # Выдаём теги новым держателям 3-15 места
    for new_tg in new_top3:
        if new_tg not in stored_top3 and not await _is_admin(new_tg):
            existing_tags = get_user_tags(int(new_tg))
            logger.debug(f"tag_manager: F3 check for {new_tg}: existing_tags={existing_tags}, in_stored={new_tg in stored_top3}")
            if "VIP" not in existing_tags:
                try:
                    await add_user_tag(int(new_tg), "F3", bot=bot, chat_id=chat_id)
                    logger.info(f"tag_manager: refresh_fissure_top_tags: F3 -> {new_tg}")
                except Exception as e:
                    logger.error(f"tag_manager: refresh_fissure_top_tags: failed to set F3 for {new_tg}: {e}")

    set_config('current_F3_telegram_ids', ','.join(str(x) for x in new_top3))
