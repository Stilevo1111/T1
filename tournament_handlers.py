"""Боевые команды турнира: регистрация, сетка и счёт матча.

Заменяет прежнюю фичу «Список матчей»: вместо ленты личных игр бот ведёт
турнир — запись по кнопке, раскладка команд по рангам, BO3 до двух побед
и персональная сетка, где значки стоят только на пути игрока.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import tournament as T
from config import settings

logger = logging.getLogger(__name__)

# Префиксы callback'ов: по ним бот понимает, какое действие запросили.
CB_JOIN = "tour_join:"
CB_BRACKET = "tour_bracket:"
CB_SCORE = "tour_score:"

SCORE_BUTTONS = ("2:0", "2:1", "0:2", "1:2")


def _admin_id():
    return getattr(settings, 'ADMIN_CHAT_ID', None)


def _escape(text) -> str:
    """Экранирование для Telegram HTML: название турнира задаёт человек."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _viewer_id(update: Update) -> int:
    user = update.effective_user
    return user.id if user else 0


def _user_rank_tier(telegram_id: int) -> int:
    """Ранг игрока из профиля; при отсутствии профиля — Herald."""
    try:
        from database import get_user
        return (get_user(telegram_id) or {}).get('rank_tier') or 0
    except Exception as e:  # pragma: no cover - зависит от БД
        logger.warning("tournament: не удалось получить ранг %s: %s", telegram_id, e)
        return 0


def _current_tournament(chat_id: int):
    """Текущий турнир чата: незакрытый, иначе последний завершённый."""
    active = T.active_tournament(chat_id)
    if active:
        return active
    rows = T._read(
        f"SELECT * FROM tournaments WHERE chat_id = {T._q()}"
        f" ORDER BY id DESC LIMIT 1", (chat_id,))
    return rows[0] if rows else None


async def _send_bracket(message, tournament: dict):
    """Присылает сетку персонально: значки только на пути того, кто смотрит."""
    tid = int(tournament['id'])
    viewer_id = message.from_user.id if message.from_user else 0

    text = (f"{T.tournament_summary(tid)}\n\n"
            f"{T.render_bracket_text(tid, viewer_id)}")

    match = T.current_match(tid, viewer_id)
    rows = []
    if match:
        rows.append([InlineKeyboardButton(
            "🆚 Мой матч", callback_data=f"{CB_SCORE}{tid}")])
    rows.append([InlineKeyboardButton(
        "🔄 Обновить", callback_data=f"{CB_BRACKET}{tid}")])

    await message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
        disable_web_page_preview=True,
    )


async def tour_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tour — турнир чата: регистрация, сетка или чемпион."""
    chat = update.effective_chat
    if chat is None:
        return

    tournament = _current_tournament(chat.id)
    if not tournament:
        await chat.send_message(
            "🏆 <b>Боевой кубок Fissure</b>\n"
            "В этом чате ещё нет турнира.\n"
            "Создать его может администратор: /newtour",
            parse_mode="HTML",
        )
        return

    tid = int(tournament['id'])
    if tournament.get('status') != 'registration':
        await _send_bracket(update.effective_message, tournament)
        return

    # Регистрация: ранг берём из профиля, порога нет.
    tier = _user_rank_tier(_viewer_id(update))
    already = any(p.get('telegram_id') == _viewer_id(update)
                  for p in T.list_players(tid))

    rows = []
    if not already:
        rows.append([InlineKeyboardButton(
            "🎮 Принять участие", callback_data=f"{CB_JOIN}{tid}")])
    rows.append([InlineKeyboardButton(
        "📊 Сетка", callback_data=f"{CB_BRACKET}{tid}")])

    hint = ("Вы уже записаны." if already else
            f"Ваш ранг: {T.rank_name(tier)}. Порога нет — играют все.")
    await chat.send_message(
        f"{T.tournament_summary(tid)}\n\n{hint}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def newtour_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/newtour [название] — создать турнир. Только для администратора."""
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return

    admin_id = _admin_id()
    if not admin_id or user.id != admin_id:
        await chat.send_message("⛔ Создавать турниры может только администратор.")
        return

    title = " ".join(context.args).strip() or "Боевой кубок Fissure"
    tid = T.create_tournament(title, chat.id, user.id)
    if not tid:
        await chat.send_message("❌ Не удалось создать турнир.")
        return

    logger.info("tournament: создан турнир %s в чате %s", tid, chat.id)
    await chat.send_message(
        f"🏆 <b>{_escape(title)}</b>\n"
        "Регистрация открыта. Участие у любого ранга, "
        "баланс команд — по рангам.\n"
        "Нажмите кнопку, чтобы записаться.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎮 Принять участие",
                                 callback_data=f"{CB_JOIN}{tid}"),
        ]]),
    )


JOIN_REASONS = {
    'exists': "Вы уже записаны на этот турнир.",
    'already': "Вы уже записаны на этот турнир.",
    'full': "Регистрация закрыта: турнир заполнен.",
    'closed': "Регистрация уже закрыта.",
}


async def tour_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запись на турнир по кнопке «Принять участие»."""
    query = update.callback_query
    await query.answer()

    tid = int(query.data.split(":")[1])
    user = update.effective_user
    if user is None:
        return

    tier = _user_rank_tier(user.id)
    res = T.join(tid, user.id, user.username or "", tier)

    if not res['ok']:
        await query.edit_message_text(
            JOIN_REASONS.get(res.get('reason'), "Не удалось записаться."))
        return

    await query.edit_message_text(
        f"✅ <b>Вы записаны</b>\n"
        f"Слот участника закреплён за вами.\n"
        f"Ваш ранг: {T.rank_name(tier)}.\n\n"
        "Когда команды будут собраны, капитаны создадут лобби "
        "(название, сервер и пароль), а игра пойдёт до двух побед.",
        parse_mode="HTML",
    )


async def tour_bracket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать сетку по кнопке."""
    query = update.callback_query
    await query.answer()

    tid = int(query.data.split(":")[1])
    tournament = T.get_tournament(tid)
    if not tournament:
        await query.edit_message_text("Турнир не найден.")
        return
    await _send_bracket(query.message, tournament)


def _score_keyboard(tid: int) -> InlineKeyboardMarkup:
    """Кнопки счёта: значения отправляются от перспективы нажавшего."""
    rows = [[InlineKeyboardButton(s, callback_data=f"{CB_SCORE}{tid}:{s}")
             for s in SCORE_BUTTONS[:2]],
            [InlineKeyboardButton(s, callback_data=f"{CB_SCORE}{tid}:{s}")
             for s in SCORE_BUTTONS[2:]],
            [InlineKeyboardButton("🔙 Сетка", callback_data=f"{CB_BRACKET}{tid}")]]
    return InlineKeyboardMarkup(rows)


async def tour_score_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор счёта своего матча: первое нажатие показывает кнопки."""
    query = update.callback_query
    await query.answer()

    tid = int(query.data.split(":")[1])
    user = update.effective_user
    if user is None:
        return

    # Формат "tour_score:<tid>" — показать кнопки; "tour_score:<tid>:<счёт>" — принять счёт.
    parts = query.data.split(":")
    if len(parts) == 2:
        await query.edit_message_text(
            "Отправьте счёт серии — играем BO3 до двух побед.\n"
            "Счёт считается от вашей команды: 2:0 и 2:1 — вы выиграли, "
            "0:2 и 1:2 — проиграли.",
            parse_mode="HTML",
            reply_markup=_score_keyboard(tid),
        )
        return

    try:
        first, second = int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        await query.answer("Неверный счёт.", show_alert=True)
        return

    res = T.report_score(tid, user.id, first, second)
    if not res['ok']:
        await query.answer("Матч уже закрыт или вы не участвуете.", show_alert=True)
        return

    if not res['finished']:
        await query.edit_message_text(
            f"Счёт принят: {first}:{second}.\n"
            "Серия ещё не закрыта — нужно до двух побед.",
            reply_markup=_score_keyboard(tid),
        )
        return

    tournament = T.get_tournament(tid) or {}
    champ = T.champion(tid)
    lines = [f"✅ Серия закрыта: {first}:{second}"]
    if champ and tournament.get('status') == 'finished':
        lines.append(f"\n🏆 Чемпион: <b>{_escape(champ['team_name'])}</b>")
    elif res.get('advanced'):
        lines.append("\nКоманда проходит в следующий раунд.")

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Сетка", callback_data=f"{CB_BRACKET}{tid}"),
        ]]),
    )


def register_tournament_handlers(app):
    """Подключает команды и кнопки турнира к приложению."""
    from telegram.ext import CommandHandler, CallbackQueryHandler

    app.add_handler(CommandHandler("tour", tour_command))
    app.add_handler(CommandHandler("newtour", newtour_command))
    app.add_handler(CallbackQueryHandler(tour_join_callback, pattern=f"^{CB_JOIN}"))
    app.add_handler(CallbackQueryHandler(tour_bracket_callback, pattern=f"^{CB_BRACKET}"))
    app.add_handler(CallbackQueryHandler(tour_score_callback, pattern=f"^{CB_SCORE}"))


