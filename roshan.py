"""Roshan event: interactive Aegis/Cheese stealing.

The event fires on a /fissure roll. The player "kills Roshan", gets a fissure
reward, and an inline button opens a short window in which every other player
can try to steal the Aegis. After the window closes, each claimer is randomly
assigned one of the three items; if nobody pressed the button the killer keeps
the Aegis alone.

Multi-instance safety
---------------------
Unlike techies.py, session state here lives in the database, not in a module
dict. On Render a button press and the timeout worker can land on two different
containers, so an in-memory session would either lose the reward or pay it out
twice. The single serialization point is:

    UPDATE roshan_sessions SET resolved = 1 WHERE session_id = ? AND resolved = 0

Only the caller whose rowcount == 1 distributes items and edits the message.
The other instance silently gives up.
"""

import asyncio
import logging
import random
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot_utils import make_clickable
from constants import (
    ROSHAN_AEGIS_EFFECTS,
    ROSHAN_CHEESE_EFFECTS,
    ROSHAN_REFRESHER_EFFECTS,
    ROSHAN_SESSION_TTL,
    ROSHAN_STEAL_WINDOW_SEC,
    ROSHAN_STEAL_TEXTS,
    ROSHAN_TEXTS,
    get_banner_path,
)

logger = logging.getLogger(__name__)

AEGIS = "aegis"
CHEESE = "cheese"
REFRESHER = "refresher"
ITEM_NAMES = (AEGIS, CHEESE, REFRESHER)

ITEM_LABELS = {AEGIS: "🧿 АЕГИС", CHEESE: "🧀 СЫР", REFRESHER: "🔄 РЕФРЕШЕР"}
# What the artifact actually does, per rolls.py. The closing message reads one
# of these straight after the name: a group announcement needs the real effect,
# and the interesting part of the Aegis is that a positive roll keeps it.
ITEM_EFFECTS = {
    AEGIS: ROSHAN_AEGIS_EFFECTS, 
    CHEESE: ROSHAN_CHEESE_EFFECTS,
    REFRESHER: ROSHAN_REFRESHER_EFFECTS,
}

# Strong references to pending window timers, otherwise the event loop may
# garbage-collect a sleeping task before it fires.
_ACTIVE_TIMERS: set = set()


# =====================
# SCHEMA
# =====================

def ensure_roshan_schema() -> None:
    """Create the Roshan tables. Must run on EVERY start, not behind SCHEMA_VERSION.

    init_db() takes a fast path when schema_version already matches and skips
    all DDL, so tables declared only in the full block would never appear on an
    already-deployed database. This mirrors what dota_mmr.py does for
    public_player_matches.
    """
    from database import Database, get_db_type

    is_pg = "postgres" in get_db_type()
    db = Database()
    # Dialect branches differ deliberately: SQLite has no BIGINT and no
    # SERIAL, and the codebase keeps separate CREATE TABLE statements per
    # dialect for exactly this reason (see dota_mmr.py:1930-1996).
    if is_pg:
        db.execute_query("""
            CREATE TABLE IF NOT EXISTS roshan_sessions (
                session_id TEXT PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                msg_id BIGINT,
                killer_id BIGINT NOT NULL,
                killer_name TEXT,
                reward REAL DEFAULT 0,
                resolved INTEGER DEFAULT 0,
                created_at REAL
            )
        """)
        db.execute_query("""
            CREATE TABLE IF NOT EXISTS roshan_claimers (
                session_id TEXT NOT NULL,
                telegram_id BIGINT NOT NULL,
                claimed_at REAL,
                PRIMARY KEY (session_id, telegram_id)
            )
        """)
    else:
        db.execute_query("""
            CREATE TABLE IF NOT EXISTS roshan_sessions (
                session_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                msg_id INTEGER,
                killer_id INTEGER NOT NULL,
                killer_name TEXT,
                reward REAL DEFAULT 0,
                resolved INTEGER DEFAULT 0,
                created_at REAL
            )
        """)
        db.execute_query("""
            CREATE TABLE IF NOT EXISTS roshan_claimers (
                session_id TEXT NOT NULL,
                telegram_id INTEGER NOT NULL,
                claimed_at REAL,
                PRIMARY KEY (session_id, telegram_id)
            )
        """)


def _ph() -> str:
    from database import get_db_type

    return "%s" if "postgres" in get_db_type() else "?"


def _row_get(row, key: str, index: int = 0):
    return row[key] if isinstance(row, dict) else row[index]


def create_session(session_id: str, chat_id: int, msg_id: int, killer_id: int,
                   killer_name: str, reward: float) -> None:
    from database import Database

    p = _ph()
    Database().execute_query(
        f"INSERT INTO roshan_sessions "
        f"(session_id, chat_id, msg_id, killer_id, killer_name, reward, resolved, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, 0, {p})",
        (session_id, chat_id, msg_id, killer_id, killer_name, reward, time.time()),
    )


def add_claimer(session_id: str, telegram_id: int) -> bool:
    """Register a claim. False if already registered or the window is closed.

    The uniqueness rule (PRIMARY KEY on session_id + telegram_id) means a
    player pressing ten times still occupies exactly one slot, so spamming the
    button cannot improve their odds.
    """
    from database import Database, get_db_type

    db = Database()
    p = _ph()
    if "postgres" in get_db_type():
        inserted = db.execute_query(
            f"INSERT INTO roshan_claimers (session_id, telegram_id, claimed_at) "
            f"VALUES ({p}, {p}, {p}) ON CONFLICT (session_id, telegram_id) DO NOTHING",
            (session_id, telegram_id, time.time()),
        )
    else:
        inserted = db.execute_query(
            f"INSERT OR IGNORE INTO roshan_claimers (session_id, telegram_id, claimed_at) "
            f"VALUES ({p}, {p}, {p})",
            (session_id, telegram_id, time.time()),
        )
    if int(inserted or 0) == 0:
        return False

    row = db.execute_query(
        f"SELECT resolved FROM roshan_sessions WHERE session_id = {p}",
        (session_id,),
        fetch="one",
    )
    if not row:
        return False
    return not int(_row_get(row, "resolved") or 0)


def load_session(session_id: str) -> dict | None:
    from database import Database

    row = Database().execute_query(
        f"SELECT session_id, chat_id, msg_id, killer_id, killer_name, reward, resolved "
        f"FROM roshan_sessions WHERE session_id = {_ph()}",
        (session_id,),
        fetch="one",
    )
    if not row:
        return None
    # Normalize to dict (PostgreSQL returns dict, SQLite returns tuple)
    if isinstance(row, dict):
        return row
    # SQLite tuple: (session_id, chat_id, msg_id, killer_id, killer_name, reward, resolved)
    return {
        "session_id": row[0],
        "chat_id": row[1],
        "msg_id": row[2],
        "killer_id": row[3],
        "killer_name": row[4],
        "reward": row[5],
        "resolved": row[6],
    }


def load_claimers(session_id: str) -> list[int]:
    from database import Database

    rows = Database().execute_query(
        f"SELECT telegram_id FROM roshan_claimers WHERE session_id = {_ph()}",
        (session_id,),
        fetch="all",
    ) or []
    return [int(_row_get(r, "telegram_id")) for r in rows]


def claim_resolution(session_id: str) -> bool:
    """Atomically take ownership of resolving this session.

    True only for the single caller that flips resolved 0 -> 1. Both Render
    instances may call this; only one sees rowcount == 1.
    """
    from database import Database

    updated = Database().execute_query(
        f"UPDATE roshan_sessions SET resolved = 1 "
        f"WHERE session_id = {_ph()} AND resolved = 0",
        (session_id,),
    )
    return int(updated or 0) > 0


def purge_expired_sessions() -> None:
    """Best-effort cleanup of long-finished sessions."""
    from database import Database

    cutoff = time.time() - ROSHAN_SESSION_TTL
    db = Database()
    p = _ph()
    try:
        db.execute_query(
            f"DELETE FROM roshan_claimers WHERE session_id IN "
            f"(SELECT session_id FROM roshan_sessions WHERE created_at < {p})",
            (cutoff,),
        )
        db.execute_query(f"DELETE FROM roshan_sessions WHERE created_at < {p}", (cutoff,))
    except Exception as e:
        logger.debug(f"roshan: purge skipped: {e}")


# =====================
# DISTRIBUTION
# =====================

def distribute_items(session_id: str) -> dict[int, list[str]]:
    """Hand out items based on claimers.

    Distribution rules:
    - If NO claimers: the killer keeps only the Aegis.
    - If claimers EXIST: distribute ALL 3 items randomly among claimers.
      Each claimer can receive at most one item (random selection).
      Killer never gets an item here: the callback refuses their own press,
      so they can never be in the claimers list.

    Refresher also grants an immediate free roll (resets cooldown).

    Returns a dict mapping telegram_id -> list of item names.
    """
    from database import grant_item, add_free_roll

    session = load_session(session_id)
    if not session:
        return {}

    claimers = load_claimers(session_id)
    killer_id = int(session.get("killer_id", 0))

    awarded: dict[int, list[str]] = {}

    if not claimers:
        # Nobody pressed the button, so the killer keeps the whole drop - but
        # only the Aegis. Cheese and Refresher are the reward for actually
        # taking the risk of the steal window; handing all three to the killer
        # for free removed every reason to press the button and let one player
        # bank the full loot on a single roll.
        try:
            if grant_item(killer_id, AEGIS):
                awarded[killer_id] = [AEGIS]
        except Exception as e:
            logger.warning(f"roshan: grant_item failed for killer/{killer_id}/{AEGIS}: {e}")
        return awarded

    # Claimers exist - distribute 3 items among claimers.
    # The killer is deliberately NOT added to the pool: handle_roshan_button
    # refuses their own press, so they can never appear in `claimers`, and
    # appending them here let them collect an item they never went into the
    # pit for (and, if they were unregistered, silently ate the item).
    potential_recipients = list(claimers)

    items_list = list(ITEM_NAMES)
    random.shuffle(items_list)
    random.shuffle(potential_recipients)

    # Track recipients who already got an item (each gets at most one)
    recipients_with_items = set()

    for item in items_list:
        for uid in potential_recipients:
            if uid in recipients_with_items:
                continue
            try:
                if grant_item(uid, item):
                    if uid not in awarded:
                        awarded[uid] = []
                    awarded[uid].append(item)
                    recipients_with_items.add(uid)
                    # Refresher grants immediate free roll
                    if item == REFRESHER:
                        add_free_roll(uid, 1)
                    break
            except Exception as e:
                logger.warning(f"roshan: grant_item failed for {uid}/{item}: {e}")

    return awarded


# =====================
# KEYBOARD / TEXT
# =====================

def build_roshan_keyboard(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Своровать",
            callback_data=f"roshan_steal_{session_id}",
            api_kwargs={"style": "danger"},
        )]
    ])


def build_roshan_text(display_username: str, claimers: int = 0) -> str:
    """The drop announcement.

    Built as labelled blocks rather than one run of prose: the roll header, the
    lore beat, the drop, and the window. A player who only wants the window
    should find it without reading the lore, and a player who only wants the
    lore should not have to skip past mechanics.
    """
    blocks = [
        f"🎲 {display_username} свалил Рошана",
        random.choice(ROSHAN_TEXTS),
        random.choice(ROSHAN_STEAL_TEXTS).format(window=ROSHAN_STEAL_WINDOW_SEC),
    ]
    if claimers:
        blocks.append(f"👥 Нажали: {claimers}")
    return "\n\n".join(blocks)


def build_result_text(
    killer_name: str,
    reward: float,
    awarded: dict[int, list[str] | str],
    winner_names: dict[int, str],
    loser_names: list[str],
) -> str:
    """Closing message: who got what, and what it does to their next roll.

    One line per artifact. The earlier layout stacked a header and an indented
    sub-line under every item, which turned a five line summary into a wall of
    columns; the reader only ever needed the artifact, its owner and its effect.
    The header is the lore beat, the second line is the kill and the reward.
    
    Accepts both dict[int, list[str]] (new format) and dict[int, str] (legacy).
    """
    blocks = [
        "🪤 Рошан пал. Проклятие Торговца свершилось снова.",
        f"🪙 Рошана убил <b>{killer_name}</b> +{reward:.1f} см",
    ]

    for uid, items in awarded.items():
        # Normalize to list for backward compatibility
        if isinstance(items, str):
            items = [items]
        if not items:
            continue
        name = winner_names.get(uid) or f"игрок {uid}"
        items_text = " и ".join([ITEM_LABELS[item] for item in items])
        effects = [random.choice(ITEM_EFFECTS[item]) for item in items]
        effects_text = ", ".join(effects)
        blocks.append(
            f"{items_text} достался <b>{name}</b> — {effects_text}"
        )

    if not awarded:
        blocks.append("Ничего не своровали.")

    return "\n\n".join(blocks)


# =====================
# EVENT
# =====================

async def handle_roshan_event(
    bot,
    chat_id: int,
    user: dict,
    user_obj,
    display_username: str,
    now: float,
    update_fissure,
    set_last_bot_message,
    schedule_delete,
    job_queue=None,
    record_recent_fissure_roll=None,
) -> None:
    """Fire the Roshan event: pay the killer, open the stealing window."""
    from rolls import calculate_roshan_reward

    current_fissure = user.get("fissure", 0) or 0
    reward = calculate_roshan_reward(current_fissure)
    new_fissure = max(0.1, current_fissure + reward)

    session_id = f"{chat_id}_{int(now)}"
    text = build_roshan_text(display_username)
    keyboard = build_roshan_keyboard(session_id)

    banner = get_banner_path("roshan")
    msg = None
    if banner and banner.exists():
        try:
            msg = await bot.send_photo(
                chat_id=chat_id, photo=str(banner), caption=text,
                reply_markup=keyboard, parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"roshan: photo send failed, falling back to text: {e}")
    if msg is None:
        msg = await bot.send_message(
            chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML",
        )

    # Persist the session BEFORE the roll bookkeeping so a press can never
    # arrive before its row exists.
    await asyncio.to_thread(
        create_session, session_id, chat_id, msg.message_id,
        user_obj.id, display_username, reward,
    )
    await asyncio.to_thread(
        update_fissure, user_obj.id, new_fissure, now, reward,
        last_message_id=msg.message_id,
    )
    # Deliberately NOT set_last_bot_message: that key is a "delete this before
    # the next roll" slot, and the next /fissure wipes it via
    # delete_last_bot_message. Registering the Roshan drop there meant any roll
    # during the 45s window deleted the button out from under the players, and
    # the window worker then failed to edit a message that no longer existed,
    # so the result was never posted. The drop is edited in place instead, and
    # it must survive until the window closes.

    if record_recent_fissure_roll:
        record_recent_fissure_roll(
            user_obj.id, user_obj.username or str(user_obj.id), reward,
            new_fissure, cascade=0, event_type="roshan",
        )

    _start_timer(bot, session_id, ROSHAN_STEAL_WINDOW_SEC, schedule_delete)


def _start_timer(bot, session_id: str, delay: int, schedule_delete=None) -> None:
    task = asyncio.create_task(
        _window_worker(bot, session_id, delay),
        name=f"roshan_window_{session_id}",
    )
    # Keep a reference so the task is not garbage collected mid-sleep.
    _ACTIVE_TIMERS.add(task)
    task.add_done_callback(_ACTIVE_TIMERS.discard)


async def _window_worker(bot, session_id: str, delay: int) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    try:
        await resolve_session(bot, session_id)
    except Exception as e:
        logger.error(f"roshan: window worker failed for {session_id}: {e}", exc_info=True)
        try:
            await asyncio.to_thread(purge_expired_sessions)
        except Exception:
            pass


async def resolve_session(bot, session_id: str) -> None:
    """Close the window, hand out items, edit the message. Exactly-once."""
    session = await asyncio.to_thread(load_session, session_id)
    if not session:
        return

    won = await asyncio.to_thread(claim_resolution, session_id)
    if not won:
        logger.info(f"roshan: session {session_id} already resolved elsewhere")
        return

    awarded = await asyncio.to_thread(distribute_items, session_id)
    claimers = await asyncio.to_thread(load_claimers, session_id)

    # Names are needed for every presser, not just the winners: the people who
    # pressed and came away empty-handed are the ones the message used to
    # reduce to a bare count.
    winner_names: dict[int, str] = {}
    if claimers or awarded:
        from database import get_user

        for uid in set(claimers) | set(awarded):
            try:
                u = await asyncio.to_thread(get_user, uid)
            except Exception:
                u = None
            name = (u or {}).get("username") or f"игрок {uid}"
            winner_names[uid] = make_clickable(name, uid)

    killer_id = int(session["killer_id"])
    loser_names = [
        winner_names.get(uid, f"игрок {uid}")
        for uid in claimers
        if uid not in awarded and uid != killer_id
    ]

    text = build_result_text(
        session.get("killer_name") or "убийца Рошана",
        float(session.get("reward") or 0.0),
        awarded,
        winner_names,
        loser_names,
    )

    chat_id = int(session["chat_id"])
    msg_id = session.get("msg_id")
    edited = False
    if msg_id:
        try:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=int(msg_id),
                caption=text, parse_mode="HTML", reply_markup=None,
            )
            edited = True
        except Exception:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=int(msg_id),
                    text=text, parse_mode="HTML", reply_markup=None,
                )
                edited = True
            except Exception as e:
                # The message can be gone (deleted by a moderator or by a
                # client-side cleanup) or too old to edit. That is not a reason
                # to drop the result: the players still have to learn who got
                # what, so fall through and post it as a new message.
                logger.info(
                    f"roshan: could not edit result message {msg_id}, "
                    f"sending a new one instead: {e}"
                )

    if not edited:
        try:
            banner = get_banner_path("roshan")
            if banner and banner.exists():
                await bot.send_photo(
                    chat_id=chat_id, photo=str(banner), caption=text, parse_mode="HTML",
                )
            else:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"roshan: could not send result message: {e}", exc_info=True)


# =====================
# CALLBACK
# =====================

async def handle_roshan_button(update: ContextTypes.DEFAULT_TYPE,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the '🔓 В яму' press."""
    query = update.callback_query
    data = query.data or ""

    if not data.startswith("roshan_steal_"):
        await query.answer()
        return

    session_id = data[len("roshan_steal_"):]
    user_id = query.from_user.id

    session = await asyncio.to_thread(load_session, session_id)
    if not session:
        await query.answer("🪤 Этот Рошан давно ушёл обратно в яму.", show_alert=True)
        return

    if int(session["resolved"] or 0):
        await query.answer("🔓 Окно закрыто, добыча разобрана.", show_alert=True)
        return

    if user_id == int(session["killer_id"]):
        await query.answer("🪙 Ты его и так убил. У себя не покрадушь.", show_alert=True)
        return

    ok = await asyncio.to_thread(add_claimer, session_id, user_id)
    if not ok:
        await query.answer("🔓 Ты уже в деле. Или окно закрылось.", show_alert=True)
        return

    count = len(await asyncio.to_thread(load_claimers, session_id))
    await query.answer(f"🔓 Ты в деле! Нажали: {count}", show_alert=False)
