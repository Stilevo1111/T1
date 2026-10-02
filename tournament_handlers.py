"""Боевые команды турнира: регистрация, сетка и счёт матча.

Заменяет прежнюю фичу «Список матчей»: вместо ленты личных игр бот ведёт
турнир — запись по кнопке, раскладка команд по рангам, BO3 до двух побед
и персональная сетка, где значки стоят только на пути игрока.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import tournament as T
from tournament import TEAM_SIZE
from config import settings

logger = logging.getLogger(__name__)

# Префиксы callback'ов: по ним бот понимает, какое действие запросили.
CB_JOIN = "tour_join:"
CB_BRACKET = "tour_bracket:"
CB_SCORE = "tour_score:"
CB_START = "tour_start:"
CB_LOBBY = "tour_lobby:"
CB_SERVER = "tour_server:"

SCORE_BUTTONS = ("2:0", "2:1", "0:2", "1:2")

# Серверы для лобби. Бот не знает пинг игроков, поэтому предлагает выбор,
# а не угадывает: неверный сервер ломает игру сильнее лишнего клика.
LOBBY_SERVERS = ("EU East", "EU West", "RU East", "US West")


def _admin_id():
    return getattr(settings, 'ADMIN_CHAT_ID', None)


def _is_admin(telegram_id: int) -> bool:
    admin_id = _admin_id()
    return bool(admin_id) and telegram_id == admin_id


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
    """Текущий турнир чата: незакрытый, иначе последний завершённый.

    Схему создаём здесь же: до первого /newtour таблиц ещё нет, а игрок
    может нажать /tour раньше — без этого чтение падало с UndefinedTable.
    ensure_schema() идемпотентна, так что лишних запросов не добавляет.
    """
    try:
        active = T.active_tournament(chat_id)
    except Exception:
        logger.info("tournament: создаём схему при первом обращении")
        T.ensure_schema()
        active = T.active_tournament(chat_id)
    if active:
        return active
    rows = T._read(
        f"SELECT * FROM tournaments WHERE chat_id = {T._q()}"
        f" ORDER BY id DESC LIMIT 1", (chat_id,))
    return rows[0] if rows else None


async def _send_bracket(message, tournament: dict, viewer_id: int):
    """Присылает сетку персонально: значки только на пути того, кто смотрит.

    `viewer_id` передаётся явно, а не берётся из `message.from_user`: при
    вызове из колбэка мы отвечаем на сообщение бота, у которого from_user —
    сам бот. Из-за этого сетка приходила без значков и без кнопки «Мой матч».
    """
    tid = int(tournament['id'])

    text = (f"{T.tournament_summary(tid)}\n\n"
            f"{T.render_bracket_text(tid, viewer_id)}")

    match = T.current_match(tid, viewer_id)
    rows = []
    if match:
        # Кнопку лобби показываем только капитану: он и создаёт его.
        team = T.player_team(tid, viewer_id)
        if team and team.get('captain_id') == viewer_id:
            rows.append([InlineKeyboardButton(
                "🎮 Создать лобби", callback_data=f"{CB_LOBBY}{tid}")])
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
        await _send_bracket(update.effective_message, tournament, _viewer_id(update))
        return

    # Регистрация: ранг берём из профиля, порога нет.
    tier = _user_rank_tier(_viewer_id(update))
    already = any(p.get('telegram_id') == _viewer_id(update)
                  for p in T.list_players(tid))

    rows = []
    if not already:
        rows.append([InlineKeyboardButton(
            "🎮 Принять участие", callback_data=f"{CB_JOIN}{tid}")])
    # Стартовать турнир может только администратор: до этого момента
    # команды не собраны, сетки нет и матчи невозможны.
    reg_players = T.count_players(tid)
    reg_needed = _players_needed_for_two_teams(tid)
    if _is_admin(_viewer_id(update)) and reg_players >= reg_needed:
        rows.append([InlineKeyboardButton(
            "▶️ Начать турнир", callback_data=f"{CB_START}{tid}")])
    rows.append([InlineKeyboardButton(
        "📊 Сетка", callback_data=f"{CB_BRACKET}{tid}")])

    hint = ("Вы уже записаны." if already else
            f"Ваш ранг: {T.rank_name(tier)}. Порога нет — играют все.")
    if _is_admin(_viewer_id(update)) and reg_players < reg_needed:
        hint += f"\nДля старта нужно {reg_needed} участников, сейчас {reg_players}."
    await chat.send_message(
        f"{T.tournament_summary(tid)}\n\n{hint}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


def _players_needed_for_two_teams(tid: int) -> int:
    """Сколько игроков нужно, чтобы получить две команды турнира."""
    tournament = T.get_tournament(tid) or {}
    size = int(tournament.get('team_size') or TEAM_SIZE)
    return max(2, size * 2)


def _registration_keyboard(tid: int, viewer_id: int) -> InlineKeyboardMarkup:
    """Кнопки во время регистрации.

    Кнопка старта доступна только администратору и только когда участников
    хватает на команды. Раньше она жила исключительно в /tour, поэтому
    нажать её можно было лишь вручную напечатав команду.
    """
    rows = []
    players = T.count_players(tid)
    # Матч возможен, когда участников хватает на ДВЕ полные команды.
    needed = _players_needed_for_two_teams(tid)
    if _is_admin(viewer_id) and players >= needed:
        rows.append([InlineKeyboardButton(
            f"▶️ Начать турнир ({players} в регистрации)",
            callback_data=f"{CB_START}{tid}")])
    rows.append([InlineKeyboardButton(
        "📊 Сетка", callback_data=f"{CB_BRACKET}{tid}")])
    return InlineKeyboardMarkup(rows)


def _parse_newtour_args(args) -> tuple[str, int]:
    """Разбирает /newtour [название] [размер].

    Последний числовой аргумент считается размером команды — так можно
    сделать тестовый турнир вдвоём: /newtour Тест 1.
    """
    title_parts = []
    team_size = TEAM_SIZE
    for raw in args:
        text = raw.strip()
        if text.isdigit() and 1 <= int(text) <= 10:
            team_size = int(text)
        elif text:
            title_parts.append(text)
    return " ".join(title_parts) or "Боевой кубок Fissure", team_size


async def newtour_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/newtour [название] [размер] — создать турнир. Только для администратора."""
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return

    admin_id = _admin_id()
    if not admin_id or user.id != admin_id:
        await chat.send_message("⛔ Создавать турниры может только администратор.")
        return

    title, team_size = _parse_newtour_args(context.args)
    tid = T.create_tournament(title, chat.id, user.id, team_size=team_size)
    if not tid:
        await chat.send_message("❌ Не удалось создать турнир.")
        return

    logger.info("tournament: создан турнир %s в чате %s", tid, chat.id)
    await chat.send_message(
        f"🏆 <b>{_escape(title)}</b>\n"
        "Регистрация открыта. Участие у любого ранга, "
        "баланс команд — по рангам.\n"
        f"В команде {team_size} человек. "
        f"Нужно минимум {team_size * 2}, чтобы собрать две команды."
        "\nНажмите кнопку, чтобы записаться.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎮 Принять участие",
                                 callback_data=f"{CB_JOIN}{tid}"),
        ], [InlineKeyboardButton("📊 Сетка", callback_data=f"{CB_BRACKET}{tid}")]]),
    )
    # Админу сразу показываем кнопку старта, чтобы не искать её в /tour.
    await chat.send_message(
        "Администратору: когда участников хватит, нажмите «▶️ Начать турнир».",
        reply_markup=_registration_keyboard(tid, user.id),
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

    # После записи оставляем навигацию: раньше edit_message_text убирал все
    # кнопки, и админ терял возможность запустить турнир без /tour.
    await query.edit_message_text(
        f"✅ <b>Вы записаны</b>\n"
        f"Слот участника закреплён за вами.\n"
        f"Ваш ранг: {T.rank_name(tier)}.\n\n"
        "Когда команды будут собраны, капитаны создадут лобби "
        "(название, сервер и пароль), а игра пойдёт до двух побед.",
        parse_mode="HTML",
        reply_markup=_registration_keyboard(tid, user.id),
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
    # Зритель — тот, кто нажал кнопку, а не автор сообщения бота.
    await _send_bracket(query.message, tournament, _viewer_id(update))


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


async def tour_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """▶️ Начать — раскладывает команды по рангам и рисует сетку.

    До этого шага турнир существовал только как список участников: команды
    не были собраны, сетка пуста, и матчи невозможны.
    """
    query = update.callback_query
    await query.answer()

    tid = int(query.data.split(":")[1])
    if not _is_admin(_viewer_id(update)):
        await query.answer("Стартовать турнир может только администратор.",
                           show_alert=True)
        return

    tournament = T.get_tournament(tid)
    if not tournament or tournament.get('status') != 'registration':
        await query.answer("Регистрация уже закрыта.", show_alert=True)
        return

    teams = T.build_teams(tid)
    if not teams:
        # build_teams отказывается собирать меньше двух полных команд.
        players = T.count_players(tid)
        needed = _players_needed_for_two_teams(tid)
        await query.answer(
            f"Для старта нужно {needed} участников, сейчас {players}. "
            "Позовите ещё игроков.",
            show_alert=True)
        return

    logger.info("tournament: старт %s, команд %s", tid, len(teams))
    await query.edit_message_text("▶️ Команды собраны, сетка опубликована.")
    await query.message.reply_text(_roster_text(tid, teams), parse_mode="HTML")

    fresh = T.get_tournament(tid) or {}
    await _send_bracket(query.message, fresh, _viewer_id(update))


def _roster_text(tid: int, teams: list[dict]) -> str:
    """Составы команд.

    Steam ID намеренно не публикуем: зайти в лобби можно по коду из
    сообщения о лобби, а ID в общем чате — личные данные, которые ещё и
    ведут на профиль в Steam.
    """
    lines = ["<b>Команды собраны</b>",
             "Баланс — по рангам. Капитаны создают лобби кнопкой в своей сетке.",
             ""]
    for team in teams:
        lines.append(f"<b>{_escape(team['name'])}</b>")
        for m in team.get('members', []):
            nick = m.get('username') or f"Игрок {m.get('telegram_id')}"
            mark = "👑 " if m.get('is_captain') else ""
            lines.append(f"  • {mark}{_escape(nick)}")
        lines.append("")
    lines.append("Переименовать команду: /teamname <название> (капитан).")
    return "\n".join(lines)


def _lobby_keyboard(tid: int) -> InlineKeyboardMarkup:
    """Выбор сервера лобби."""
    rows = [
        [InlineKeyboardButton(s, callback_data=f"{CB_SERVER}{tid}:{s}")
         for s in LOBBY_SERVERS[:2]],
        [InlineKeyboardButton(s, callback_data=f"{CB_SERVER}{tid}:{s}")
         for s in LOBBY_SERVERS[2:]],
    ]
    return InlineKeyboardMarkup(rows)


def _make_code(seed: int) -> str:
    """Короткий код лобби из id матча: F + последние три цифры."""
    return f"F{str(int(seed))[-3:]}"


def _make_password(tid: int, match_id: int) -> str:
    """Пароль лобби: одинаковый для обеих команд, чтобы не переписываться."""
    return f"fissure{int(tid)}{int(match_id)}"[-8:]


async def tour_lobby_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🎮 Создать лобби — только капитан команды своего матча."""
    query = update.callback_query
    await query.answer()

    tid = int(query.data.split(":")[1])
    user = update.effective_user
    if user is None:
        return

    team = T.player_team(tid, user.id)
    if not team or team.get('captain_id') != user.id:
        await query.answer("Лобби создаёт капитан команды.", show_alert=True)
        return

    match = T.current_match(tid, user.id)
    if not match:
        await query.answer("У вас сейчас нет матча.", show_alert=True)
        return

    await query.message.reply_text(
        "Выберите сервер лобби. Название и пароль бот подставит сам — "
        "их увидит и соперник.",
        reply_markup=_lobby_keyboard(tid),
    )


async def tour_server_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сервер выбран — сохраняем лобби и публикуем его в чат."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    tid = int(parts[1])
    server = parts[2] if len(parts) > 2 else "EU East"

    user = update.effective_user
    if user is None:
        return
    team = T.player_team(tid, user.id)
    if not team or team.get('captain_id') != user.id:
        await query.answer("Лобби создаёт капитан команды.", show_alert=True)
        return
    match = T.current_match(tid, user.id)
    if not match:
        await query.answer("У вас сейчас нет матча.", show_alert=True)
        return

    tournament = T.get_tournament(tid) or {}
    title = tournament.get('title') or "Кубок"
    code = _make_code(match['id'])
    password = _make_password(tid, match['id'])
    # Название собирается автоматически: турнир · команда · раунд.
    name = f"{title} · {team['name']} · {T.label_round(int(match['round']))}"
    T.set_lobby(match['id'], code, server, name, password)

    opponent = (match.get('team2_id') if match.get('team1_id') == team['id']
                else match.get('team1_id'))
    rival = next((t['name'] for t in T.list_teams(tid) if t['id'] == opponent), "—")

    await query.edit_message_text(f"✅ Лобби создан: {server}")
    await query.message.reply_text(
        f"🎮 <b>Лобби к матчу</b>\n"
        f"Название: <b>{_escape(name)}</b>\n"
        f"Сервер: <b>{_escape(server)}</b>\n"
        f"Пароль: <code>{_escape(password)}</code>\n"
        f"Код: <code>{_escape(code)}</code>\n"
        f"Соперник: <b>{_escape(rival)}</b>\n\n"
        "Пароль одинаковый у обеих команд — заходите по нему и играйте "
        "до двух побед. После матча капитан жмёт «🆚 Мой матч» и сдаёт счёт.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🆚 Счёт матча", callback_data=f"{CB_SCORE}{tid}"),
        ]]),
        disable_web_page_preview=True,
    )


async def teamname_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/teamname <название> — капитан называет свою команду."""
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return

    tournament = _current_tournament(chat.id)
    if not tournament:
        await chat.send_message("В этом чате нет турнира.")
        return

    tid = int(tournament['id'])
    team = T.player_team(tid, user.id)
    if not team:
        await chat.send_message("Вы не участвуете в турнире.")
        return
    if team.get('captain_id') != user.id:
        await chat.send_message("Название задаёт капитан команды.")
        return

    name = " ".join(context.args).strip()
    if not name:
        await chat.send_message("Напишите название: /teamname Team Zeus")
        return
    if not T.rename_team(team['id'], name):
        await chat.send_message("Не удалось изменить название.")
        return

    await chat.send_message(f"✅ Команда теперь называется <b>{_escape(name)}</b>.",
                            parse_mode="HTML")


def register_tournament_handlers(app):
    """Подключает команды и кнопки турнира к приложению."""
    from telegram.ext import CommandHandler, CallbackQueryHandler

    # Таблицы создаём на старте, а не по первому /newtour: иначе игрок,
    # нажавший /tour раньше администратора, получит ошибку в логах.
    try:
        T.ensure_schema()
    except Exception as e:  # pragma: no cover - зависит от реальной БД
        logger.error("tournament: не удалось создать схему на старте: %s", e)

    app.add_handler(CommandHandler("tour", tour_command))
    app.add_handler(CommandHandler("newtour", newtour_command))
    app.add_handler(CommandHandler("teamname", teamname_command))
    app.add_handler(CallbackQueryHandler(tour_join_callback, pattern=f"^{CB_JOIN}"))
    app.add_handler(CallbackQueryHandler(tour_bracket_callback, pattern=f"^{CB_BRACKET}"))
    app.add_handler(CallbackQueryHandler(tour_score_callback, pattern=f"^{CB_SCORE}"))
    app.add_handler(CallbackQueryHandler(tour_start_callback, pattern=f"^{CB_START}"))
    app.add_handler(CallbackQueryHandler(tour_lobby_callback, pattern=f"^{CB_LOBBY}"))
    app.add_handler(CallbackQueryHandler(tour_server_callback, pattern=f"^{CB_SERVER}"))


