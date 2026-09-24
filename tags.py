import json
import logging

logger = logging.getLogger(__name__)

TAG_TYPES = {
    "weekly_mvp": "MVP",
    "weekly_top1": "TOP 1",
    "weekly_top2": "MMR Top-2",
    "weekly_top3": "MMR Top-3",
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
    "admin_custom": 50,
}


def get_user_tags(telegram_id: int) -> list:
    from database import get_user, get_vip_users
    user = get_user(telegram_id)
    if not user:
        return []
    raw = user.get("user_tags")
    tags = []
    if raw:
        if isinstance(raw, list):
            tags = [t for t in raw if t in TAG_TYPES]
        else:
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    tags = [t for t in data if t in TAG_TYPES]
            except Exception:
                if isinstance(raw, str) and raw in TAG_TYPES:
                    tags = [raw]

    vip_users = get_vip_users()
    if str(telegram_id) in [str(uid) for uid in vip_users] or telegram_id in vip_users:
        if "VIP" not in tags:
            tags = tags + ["VIP"]

    return tags


def _save_user_tags(telegram_id: int, tags: list) -> None:
    from database import update_user_field
    payload = json.dumps(tags, ensure_ascii=False)
    update_user_field(telegram_id, "user_tags", payload)


async def _get_chat_member_status(bot, chat_id: int, user_id: int) -> str | None:
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
        result = await bot.do_api_request(
            endpoint="setChatMemberTag",
            api_kwargs={"chat_id": chat_id, "user_id": user_id, "tag": tag},
            return_type=bool,
        )
        logger.info(f"tag_manager: {tag} tag applied to {user_id}: {result}")
        return result
    except Exception as e:
        logger.warning(f"tag_manager: setChatMemberTag failed for {user_id} ({tag}): {e}")
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


async def _apply_best_tag(bot, telegram_id: int, chat_id: int) -> bool:
    best = get_best_tag(telegram_id)
    title = TAG_TYPES.get(best, "") if best else ""

    status = await _get_chat_member_status(bot, chat_id, telegram_id)
    if status in ("member", "restricted"):
        return await _set_member_tag(bot, chat_id, telegram_id, title)
    if status in ("administrator", "creator"):
        return await _set_admin_custom_title(bot, chat_id, telegram_id, title)

    logger.debug(f"tag_manager: user {telegram_id} status={status}, skipping tag apply")
    return False


async def add_user_tag(telegram_id: int, tag_type: str, bot=None, chat_id: int | None = None) -> bool:
    if tag_type not in TAG_TYPES:
        return False
    current = get_user_tags(telegram_id)
    if tag_type in current:
        if bot and chat_id:
            return await _apply_best_tag(bot, telegram_id, chat_id)
        return True
    current.append(tag_type)
    _save_user_tags(telegram_id, current)
    logger.info(f"tag_manager: added tag {tag_type} to user {telegram_id}")
    if bot and chat_id:
        return await _apply_best_tag(bot, telegram_id, chat_id)
    return True


async def remove_user_tag(telegram_id: int, tag_type: str, bot=None, chat_id: int | None = None) -> bool:
    current = get_user_tags(telegram_id)
    if tag_type not in current:
        return False
    current = [t for t in current if t != tag_type]
    _save_user_tags(telegram_id, current)
    logger.info(f"tag_manager: removed tag {tag_type} from user {telegram_id}")
    if bot and chat_id:
        return await _apply_best_tag(bot, telegram_id, chat_id)
    return True


def get_best_tag(telegram_id: int) -> str | None:
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


async def refresh_fissure_top_tags(bot, chat_id: int, notify: bool = True) -> None:
    """Обновляет теги ТОП 1/2/3 фиссуры при смене мест в топе.

    Золото — 1 место, серебро — 2 место, бронза — 3-15 место.
    Теги забираются у предыдущих держателей при смене состава топа.
    Администраторы пропускаются — они держат свой админ-тег.
    """
    from database import get_config, get_fissure_top, set_config
    try:
        digest_chat_id = get_config('digest_chat_id')
        if digest_chat_id:
            chat_id = int(digest_chat_id)
    except Exception as e:
        logger.debug(f"tag_manager: refresh_fissure_top_tags: invalid digest_chat_id: {e}")

    if not chat_id:
        logger.info("tag_manager: refresh_fissure_top_tags: no valid chat_id")
        return

    top_users = get_fissure_top(15)
    if not top_users:
        logger.info("tag_manager: refresh_fissure_top_tags: no top users")
        return

    def _tg(u):
        return u.get('telegram_id') if u else None

    def _name(u):
        if not u:
            return ""
        return u.get('username') or u.get('steam_nickname') or str(u.get('telegram_id'))

    logger.info(f"tag_manager: refresh_fissure_top_tags: top_users count={len(top_users)}")
    if top_users:
        logger.info(f"tag_manager: top1={_tg(top_users[0]) if len(top_users) > 0 else None}")
        if len(top_users) > 1:
            logger.info(f"tag_manager: top2={_tg(top_users[1])}")
        if len(top_users) > 2:
            logger.info(f"tag_manager: top3-15={[_tg(u) for u in top_users[2:15]]}")

    current_top1 = top_users[0] if len(top_users) > 0 else None
    current_top2 = top_users[1] if len(top_users) > 1 else None
    current_top3 = [u for u in top_users[2:15]] if len(top_users) > 2 else []

    new_top1_tg = _tg(current_top1)
    new_top2_tg = _tg(current_top2)
    new_top3 = [_tg(u) for u in current_top3 if _tg(u)]

    stored_top1_tg = get_config('current_F1_telegram_id') or ""
    logger.info(f"tag_manager: stored_top1_tg={stored_top1_tg}, new_top1_tg={new_top1_tg}")

    if not stored_top1_tg and new_top1_tg:
        logger.info("tag_manager: no stored F1 tag, performing initial tag assignment")
        if not await _is_admin(bot, chat_id, int(new_top1_tg)):
            ok = await add_user_tag(int(new_top1_tg), "F1", bot=bot, chat_id=chat_id)
            if ok:
                set_config('current_F1_telegram_id', str(new_top1_tg))
                logger.info(f"tag_manager: initial F1 assignment -> {_name(current_top1)}")
            else:
                logger.error("tag_manager: failed initial F1 assignment (API)")

    # Перечитываем конфиг после первичной выдачи, чтобы избежать дубля в блоке "Выдаём новому"
    stored_top1_tg = get_config('current_F1_telegram_id') or ""

    if not get_config('current_F2_telegram_id') and new_top2_tg:
        if not await _is_admin(bot, chat_id, int(new_top2_tg)):
            ok = await add_user_tag(int(new_top2_tg), "F2", bot=bot, chat_id=chat_id)
            if ok:
                set_config('current_F2_telegram_id', str(new_top2_tg))
                logger.info(f"tag_manager: initial F2 assignment -> {_name(current_top2)}")
            else:
                logger.error("tag_manager: failed initial F2 assignment (API)")

    if not get_config('current_F3_telegram_ids'):
        for u in current_top3:
            tg = _tg(u)
            if tg and not await _is_admin(bot, chat_id, tg):
                ok = await add_user_tag(tg, "F3", bot=bot, chat_id=chat_id)
                if ok:
                    logger.info(f"tag_manager: initial F3 assignment -> {_name(u)}")
                else:
                    logger.error(f"tag_manager: failed initial F3 assignment for {tg} (API)")

    # Где упал старый топ 1?
    stored_old_top1 = None
    if stored_top1_tg:
        for u in top_users:
            if u and u.get('telegram_id') == int(stored_top1_tg):
                stored_old_top1 = u
                break

    logger.debug(f"tag_manager: stored_old_top1={stored_old_top1}")

    if stored_top1_tg and str(new_top1_tg) != str(stored_top1_tg) and int(stored_top1_tg) != 0:
        # Забираем у старого
        if not await _is_admin(bot, chat_id, int(stored_top1_tg)):
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

    # Выдаём новому — только если топ-1 изменился
    if new_top1_tg and str(new_top1_tg) != str(stored_top1_tg) and not await _is_admin(bot, chat_id, int(new_top1_tg)):
        ok = await add_user_tag(int(new_top1_tg), "F1", bot=bot, chat_id=chat_id)
        if ok:
            set_config('current_F1_telegram_id', str(new_top1_tg))
            logger.info(f"tag_manager: refresh_fissure_top_tags: F1 -> {_name(current_top1)} ({new_top1_tg})")
        else:
            logger.error(f"tag_manager: refresh_fissure_top_tags: failed to set F1 for {new_top1_tg} (API)")
    elif new_top1_tg and str(new_top1_tg) == str(stored_top1_tg):
        # Топ-1 не менялся — проверяем, есть ли тег, и выдаём если пропал
        tags = get_user_tags(int(new_top1_tg))
        if "F1" not in tags:
            ok = await add_user_tag(int(new_top1_tg), "F1", bot=bot, chat_id=chat_id)
            if ok:
                logger.info(f"tag_manager: refresh_fissure_top_tags: re-applied missing F1 to {new_top1_tg}")
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
        if not await _is_admin(bot, chat_id, int(stored_top2_tg)):
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

    # Выдаём F2 новому — только если топ-2 изменился
    if new_top2_tg and str(new_top2_tg) != str(stored_top2_tg) and not await _is_admin(bot, chat_id, int(new_top2_tg)):
        ok = await add_user_tag(int(new_top2_tg), "F2", bot=bot, chat_id=chat_id)
        if ok:
            set_config('current_F2_telegram_id', str(new_top2_tg))
            logger.info(f"tag_manager: refresh_fissure_top_tags: F2 -> {_name(current_top2)} ({new_top2_tg})")
        else:
            logger.error(f"tag_manager: refresh_fissure_top_tags: failed to set F2 for {new_top2_tg} (API)")
    elif new_top2_tg and str(new_top2_tg) == str(stored_top2_tg):
        tags = get_user_tags(int(new_top2_tg))
        if "F2" not in tags:
            ok = await add_user_tag(int(new_top2_tg), "F2", bot=bot, chat_id=chat_id)
            if ok:
                logger.info(f"tag_manager: refresh_fissure_top_tags: re-applied missing F2 to {new_top2_tg}")
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
        if old_tg not in new_top3 and not await _is_admin(bot, chat_id, int(old_tg)):
            try:
                await remove_user_tag(int(old_tg), "F3", bot=bot, chat_id=chat_id)
                logger.info(f"tag_manager: refresh_fissure_top_tags: removed F3 from {old_tg}")
            except Exception as e:
                logger.warning(f"tag_manager: refresh_fissure_top_tags: failed to remove F3 from {old_tg}: {e}")

    # Выдаём теги новым держателям 3-15 места
    successful_f3 = []
    for new_tg in new_top3:
        if new_tg not in stored_top3 and not await _is_admin(bot, chat_id, int(new_tg)):
            existing_tags = get_user_tags(int(new_tg))
            logger.debug(f"tag_manager: F3 check for {new_tg}: existing_tags={existing_tags}, in_stored={new_tg in stored_top3}")
            if "VIP" not in existing_tags:
                ok = await add_user_tag(int(new_tg), "F3", bot=bot, chat_id=chat_id)
                if ok:
                    successful_f3.append(new_tg)
                    logger.info(f"tag_manager: refresh_fissure_top_tags: F3 -> {new_tg}")
                else:
                    logger.error(f"tag_manager: refresh_fissure_top_tags: failed to set F3 for {new_tg} (API)")

    # Update config with only successfully assigned F3 holders plus those already had tag and still in top
    retained = [tg for tg in stored_top3 if tg in new_top3]
    final_f3 = list(dict.fromkeys(retained + successful_f3))  # preserve order, unique
    set_config('current_F3_telegram_ids', ','.join(str(x) for x in final_f3))


async def refresh_mmr_top_tags(bot, chat_id: int) -> None:
    """Обновляет теги MMR топа (Top-1, MMR Top-2, MMR Top-3).

    - Top-1 - единственный, выдается раз в неделю
    - MMR Top-2, MMR Top-3 - аналогично фиссурным тегам
    """
    from datetime import datetime

    from database import get_config, get_mmr_top, set_config

    try:
        digest_chat_id = get_config('digest_chat_id')
        if digest_chat_id:
            chat_id = int(digest_chat_id)
    except Exception:
        pass

    if not chat_id:
        return

    top_users = get_mmr_top(10)
    if not top_users:
        return

    current_top1 = top_users[0] if top_users else None
    current_top2 = top_users[1] if len(top_users) > 1 else None
    current_top3 = top_users[2] if len(top_users) > 2 else None

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
            member = await bot.get_chat_member(chat_id=chat_id, user_id=int(tg_id))
            return member.status in ("administrator", "creator")
        except Exception:
            return False

    now_week = tuple(datetime.now().isocalendar()[:2])

    # Top-1 (единственный, раз в неделю)
    new_top1 = _tg(current_top1)
    last_mmr_top1_week = get_config('last_mmr_top1_week')
    try:
        last_week = json.loads(last_mmr_top1_week or "{}") if last_mmr_top1_week else {}
        stored_week = tuple(last_week.get('week', [])) if last_week.get('week') else ()
        is_new_week = stored_week != now_week
    except Exception:
        is_new_week = True

    if new_top1 and is_new_week and not await _is_admin(new_top1):
        ok = await add_user_tag(int(new_top1), "weekly_top1", bot=bot, chat_id=chat_id)
        if ok:
            logger.info(f"tag_manager: MMR Top-1 -> {_name(current_top1)}")
            set_config('last_mmr_top1_week', json.dumps({'week': list(now_week)}))
        else:
            logger.error("tag_manager: failed to set MMR Top-1 (API)")

    # MMR Top-2, Top-3 (аналогично F2, F3) — с персистентным конфигом
    # Top-2
    new_top2 = _tg(current_top2)
    stored_mmr_top2 = get_config('current_mmr_top2_telegram_id')

    if stored_mmr_top2 and str(new_top2) != str(stored_mmr_top2) and int(stored_mmr_top2) != 0:
        if not await _is_admin(int(stored_mmr_top2)):
            try:
                await remove_user_tag(int(stored_mmr_top2), "weekly_top2", bot=bot, chat_id=chat_id)
                logger.info(f"tag_manager: refresh_mmr_top_tags: removed weekly_top2 from {stored_mmr_top2}")
            except Exception as e:
                logger.warning(f"tag_manager: refresh_mmr_top_tags: failed to remove weekly_top2 from {stored_mmr_top2}: {e}")

    if new_top2 and str(new_top2) != str(stored_mmr_top2) and not await _is_admin(new_top2):
        ok = await add_user_tag(int(new_top2), "weekly_top2", bot=bot, chat_id=chat_id)
        if ok:
            set_config('current_mmr_top2_telegram_id', str(new_top2))
            logger.info(f"tag_manager: refresh_mmr_top_tags: weekly_top2 -> {_name(current_top2)} ({new_top2})")
        else:
            logger.error(f"tag_manager: refresh_mmr_top_tags: failed to set weekly_top2 for {new_top2} (API)")
    elif new_top2 and str(new_top2) == str(stored_mmr_top2):
        tags = get_user_tags(int(new_top2))
        if "weekly_top2" not in tags:
            ok = await add_user_tag(int(new_top2), "weekly_top2", bot=bot, chat_id=chat_id)
            if ok:
                logger.info(f"tag_manager: refresh_mmr_top_tags: re-applied missing weekly_top2 to {new_top2}")
    else:
        set_config('current_mmr_top2_telegram_id', str(new_top2) if new_top2 else "")

    # Top-3 (только 3-е место)
    new_top3 = _tg(current_top3)
    stored_mmr_top3 = get_config('current_mmr_top3_telegram_id')

    if stored_mmr_top3 and str(new_top3) != str(stored_mmr_top3) and int(stored_mmr_top3) != 0:
        if not await _is_admin(int(stored_mmr_top3)):
            try:
                await remove_user_tag(int(stored_mmr_top3), "weekly_top3", bot=bot, chat_id=chat_id)
                logger.info(f"tag_manager: refresh_mmr_top_tags: removed weekly_top3 from {stored_mmr_top3}")
            except Exception as e:
                logger.warning(f"tag_manager: refresh_mmr_top_tags: failed to remove weekly_top3 from {stored_mmr_top3}: {e}")

    if new_top3 and str(new_top3) != str(stored_mmr_top3) and not await _is_admin(new_top3):
        ok = await add_user_tag(int(new_top3), "weekly_top3", bot=bot, chat_id=chat_id)
        if ok:
            set_config('current_mmr_top3_telegram_id', str(new_top3))
            logger.info(f"tag_manager: refresh_mmr_top_tags: weekly_top3 -> {_name(current_top3)} ({new_top3})")
        else:
            logger.error(f"tag_manager: refresh_mmr_top_tags: failed to set weekly_top3 for {new_top3} (API)")
    elif new_top3 and str(new_top3) == str(stored_mmr_top3):
        tags = get_user_tags(int(new_top3))
        if "weekly_top3" not in tags:
            ok = await add_user_tag(int(new_top3), "weekly_top3", bot=bot, chat_id=chat_id)
            if ok:
                logger.info(f"tag_manager: refresh_mmr_top_tags: re-applied missing weekly_top3 to {new_top3}")
    else:
        set_config('current_mmr_top3_telegram_id', str(new_top3) if new_top3 else "")
