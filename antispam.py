"""
Anti-spam for the Fissure bot.

Design
------
The bot must never flood a chat, but it must also never punish a user who
just joined and wants to try every button. So the limits are applied **per
action**, not per user:

* every action (a command, a reply-keyboard button, an inline button) has
  its own cooldown — repeating it too soon is answered with a friendly
  "не торопись" instead of being silently dropped;
* a soft, non-punitive ceiling stops the bot from answering a user who
  fires dozens of *different* actions per second;
* nothing is ever muted or escalated: after the nudge the user may press
  any other button immediately.

The guard is meant to be installed as a PTB handler in a group *before* the
command handlers, so an over-quota action never reaches the business logic
and never produces a bot reply.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

from telegram.ext import ApplicationHandlerStop, filters

logger = logging.getLogger(__name__)

__all__ = [
    "Action",
    "SpamDecision",
    "SpamGuard",
    "spam_guard",
    "guard_handler",
    "extract_action",
    "reset_state",
]


# ── Defaults (overridable through config.Settings) ──────────────────────────
DEFAULTS = {
    "action_cooldown": 4.0,        # default cooldown of a single action
    "nudge_cooldown": 15.0,        # how often the "не торопись" message may repeat
    "soft_window_seconds": 10.0,   # window of the soft total rate
    "soft_max_actions": 20,        # actions per window before the nudge
    "soft_cooldown": 10.0,         # wait shown when the soft rate is hit
    "max_tracked_users": 5000,
}

# Per-action overrides. Expensive commands need a longer breath, /fissure
# already has its own 3 second window inside fissure.py.
ACTION_COOLDOWNS: dict[str, float] = {
    "cmd:/fissure": 2.0,
    "cmd:/fissura": 2.0,
    "cmd:/profile": 8.0,
    "cmd:/p": 8.0,
    "cmd:/analyze": 15.0,
    "cmd:/refreshmmr": 20.0,
    "cmd:/party": 10.0,
    "cmd:/matches": 10.0,
    "cmd:/link": 10.0,
    "cmd:/story": 10.0,
    "cmd:/top": 6.0,
    "cmd:/topmmr": 6.0,
    "cmd:/info": 6.0,
}

# Friendly names of the inline buttons (callback data -> label).
CALLBACK_LABELS: dict[str, str] = {
    "roll_fissure": "🎲 Ролл Фиссуры",
    "link": "🔑 Привязать Аккаунт",
    "stats": "👤 Профиль",
    "top": "🏆 Топ Фиссур",
    "topmmr": "🏆 Топ MMR",
}

# Callbacks that must never be throttled - onboarding, greetings, tutorial.
# A brand-new user should be able to click every button once without a nudge.
EXEMPT_CALLBACKS: set[str] = {
    "greeting_good",
    "greeting_bad",
    "greeting_night",
    "greeting_morning",
    "first_roll",
    "tutorial_next",
    "tutorial_skip",
    "welcome",
}


def _load_settings() -> dict:
    """Read the anti-spam knobs from config, falling back to DEFAULTS."""
    values = dict(DEFAULTS)
    try:
        from config import settings
    except Exception as exc:  # config needs BOT_TOKEN/DATABASE_URL at import time
        logger.debug(f"antispam: config unavailable ({exc}), using defaults")
        return values

    mapping = {
        "action_cooldown": "SPAM_ACTION_COOLDOWN",
        "nudge_cooldown": "SPAM_NUDGE_COOLDOWN",
        "soft_window_seconds": "SPAM_SOFT_WINDOW",
        "soft_max_actions": "SPAM_SOFT_MAX_ACTIONS",
        "soft_cooldown": "SPAM_SOFT_COOLDOWN",
    }
    for key, attr in mapping.items():
        raw = getattr(settings, attr, None)
        if raw is None:
            continue
        try:
            values[key] = type(DEFAULTS[key])(raw)
        except (TypeError, ValueError):
            logger.warning(f"antispam: bad value for {attr}={raw!r}, keeping default")
    return values


@dataclass(frozen=True)
class Action:
    """A single thing the user asked the bot to do."""

    key: str    # identity of the action, used for the cooldown bookkeeping
    label: str  # human readable name, shown in the "не торопись" message
    cooldown_override: float | None = None  # explicit cooldown, wins over the map

    def cooldown(self, default: float) -> float:
        if self.cooldown_override is not None:
            return self.cooldown_override
        return ACTION_COOLDOWNS.get(self.key, default)


@dataclass
class SpamDecision:
    """Outcome of a single anti-spam check."""

    allowed: bool
    reason: str = ""          # "" | "repeat" | "flood"
    retry_after: float = 0.0  # seconds until the action may be repeated
    action: Action | None = None
    warn: bool = False        # True when the friendly message should be sent

    @property
    def blocked(self) -> bool:
        return not self.allowed


class SpamGuard:
    """Thread-safe per-action cooldowns with a soft, non-punitive rate cap."""

    def __init__(self, **options):
        values = dict(DEFAULTS)
        values.update(_load_settings())
        values.update({k: v for k, v in options.items() if v is not None})

        self.action_cooldown = float(values["action_cooldown"])
        self.nudge_cooldown = float(values["nudge_cooldown"])
        self.soft_window_seconds = float(values["soft_window_seconds"])
        self.soft_max_actions = max(1, int(values["soft_max_actions"]))
        self.soft_cooldown = float(values["soft_cooldown"])
        self.max_tracked_users = max(100, int(values["max_tracked_users"]))

        self._last_action: dict[tuple[int, str], float] = {}
        self._nudge_at: dict[tuple[int, str], float] = {}
        self._events: dict[int, deque[float]] = {}
        # Keep the user order and the timestamp/action maps bounded together.
        # Tracking users who only repeat a blocked action also needs an order
        # entry, so a flood cannot grow _nudge_at without bound.
        self._order: deque[int] = deque()
        self._tracked_users: set[int] = set()
        self._lock = threading.Lock()

    # -- internals ---------------------------------------------------------
    def _touch_order(self, user_id: int) -> None:
        if user_id not in self._tracked_users:
            self._tracked_users.add(user_id)
            self._order.append(user_id)
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while len(self._order) > self.max_tracked_users:
            stale = self._order.popleft()
            self._tracked_users.discard(stale)
            self._events.pop(stale, None)
            for key in [k for k in self._last_action if k[0] == stale]:
                self._last_action.pop(key, None)
            for key in [k for k in self._nudge_at if k[0] == stale]:
                self._nudge_at.pop(key, None)

    def _nudge(
        self, user_id: int, action: Action, now: float, wait: float, reason: str
    ) -> SpamDecision:
        """Build the decision for a blocked action and decide whether to speak."""
        key = (user_id, action.key)
        last_nudge = self._nudge_at.get(key, 0.0)
        speak = (now - last_nudge) >= self.nudge_cooldown
        if speak:
            self._nudge_at[key] = now
        return SpamDecision(
            allowed=False,
            reason=reason,
            retry_after=max(0.0, wait),
            action=action,
            warn=speak,
        )

    # -- public API --------------------------------------------------------
    def check(
        self, user_id: int, action: Action, now: float | None = None
    ) -> SpamDecision:
        """
        Register an action and report whether it may run.

        Repeating the very same action too soon is answered with a friendly
        nudge, different actions are never blocked by the per-action rule.
        """
        if not user_id or action is None:
            return SpamDecision(allowed=True)

        now = time.monotonic() if now is None else now
        with self._lock:
            # Admit this user to bounded tracking before touching per-user state.
            self._touch_order(user_id)
            events = self._events.setdefault(user_id, deque())
            cutoff = now - self.soft_window_seconds
            while events and events[0] < cutoff:
                events.popleft()

            # 1. Block repeated actions first. Blocked retries do not extend
            #    the user's rolling flood window.
            cooldown = action.cooldown(self.action_cooldown)
            key = (user_id, action.key)
            last = self._last_action.get(key)
            if last is not None and (now - last) < cooldown:
                return self._nudge(
                    user_id, action, now, cooldown - (now - last), reason="repeat"
                )

            # 2. Count the attempt for the aggregate ceiling, including a
            #    different action rejected by that ceiling. This stops a user
            #    from spamming distinct actions or cycling action keys forever.
            events.append(now)
            if len(events) > self.soft_max_actions:
                return self._nudge(
                    user_id, action, now, self.soft_cooldown, reason="flood"
                )

            # 3. Allow and remember the action cooldown.
            self._last_action[key] = now
            return SpamDecision(allowed=True, action=action)

    def reset(self, user_id: int | None = None) -> None:
        """Forget the state of one user (or of everybody)."""
        with self._lock:
            if user_id is None:
                self._last_action.clear()
                self._nudge_at.clear()
                self._events.clear()
                self._order.clear()
                self._tracked_users.clear()
                return
            self._events.pop(user_id, None)
            self._tracked_users.discard(user_id)
            for key in [k for k in self._last_action if k[0] == user_id]:
                self._last_action.pop(key, None)
                self._nudge_at.pop(key, None)
            try:
                self._order.remove(user_id)
            except ValueError:
                pass

    def stats(self) -> dict:
        """Snapshot of the guard state (debugging / tests)."""
        with self._lock:
            return {
                "tracked_users": len(self._tracked_users),
                "tracked_actions": len(self._last_action),
                "tracked_nudges": len(self._nudge_at),
                "action_cooldown": self.action_cooldown,
                "nudge_cooldown": self.nudge_cooldown,
                "soft_max_actions": self.soft_max_actions,
                "soft_window_seconds": self.soft_window_seconds,
            }


# ── Module level singleton ─────────────────────────────────────────────────
spam_guard = SpamGuard()

# Lazily filled cache of the reply-keyboard labels.
_MENU_BUTTONS: tuple[str, ...] | None = None


# ── Telegram glue ──────────────────────────────────────────────────────────
def _menu_button_texts() -> tuple[str, ...]:
    """Labels of the reply-keyboard buttons (lazy import, bot_utils is heavy)."""
    global _MENU_BUTTONS
    if _MENU_BUTTONS is None:
        try:
            from bot_utils import MENU_BUTTON_TEXTS

            _MENU_BUTTONS = tuple(MENU_BUTTON_TEXTS)
        except Exception:  # pragma: no cover - defensive
            _MENU_BUTTONS = ()
    return _MENU_BUTTONS


def _match_menu_button(text: str) -> str | None:
    """Return the menu button the text refers to, or None."""
    if not text:
        return None
    lowered = text.lower()
    for label in _menu_button_texts():
        label_lower = label.lower()
        if lowered == label_lower or lowered.startswith(label_lower):
            return label
    return None


def extract_action(update) -> Action | None:
    """
    Figure out which action the update asks for.

    Ordinary chat messages return None — they are not bot actions and must
    never be limited.
    """
    callback_query = getattr(update, "callback_query", None)
    if callback_query is not None:
        data = getattr(callback_query, "data", None) or ""
        if data in EXEMPT_CALLBACKS:
            # Onboarding / tutorial callbacks must never be throttled so a
            # brand-new user can click every button once without a nudge.
            return None
        label = CALLBACK_LABELS.get(data, data or "кнопку")
        return Action(key=f"cb:{data}", label=label)

    message = getattr(update, "effective_message", None)
    if message is None:
        return None
    try:
        if filters.StatusUpdate.ALL.check_update(update):
            return None
    except Exception:  # pragma: no cover - defensive, filters may change
        pass

    text = (getattr(message, "text", None) or "").strip()
    if not text:
        return None

    if text.startswith("/"):
        command = text.split()[0].split("@")[0].lower()
        return Action(key=f"cmd:{command}", label=command)

    label = _match_menu_button(text)
    if label is not None:
        return Action(key=f"btn:{label}", label=label)

    return None


def check_update(update) -> SpamDecision | None:
    """
    Check an update against the anti-spam rules.

    Returns None when the update is not a bot action (ordinary chat, service
    message, a bot) and therefore must never be limited.
    """
    user = getattr(update, "effective_user", None)
    if user is None or getattr(user, "is_bot", False):
        return None
    user_id = getattr(user, "id", None)
    if not user_id or user_id in _exempt_user_ids():
        return None

    action = extract_action(update)
    if action is None:
        return None
    return spam_guard.check(user_id, action)


def _exempt_user_ids() -> set[int]:
    """Users that must never be throttled (the bot owner)."""
    ids: set[int] = set()
    try:
        from config import settings

        admin_id = getattr(settings, "ADMIN_CHAT_ID", None)
        if admin_id:
            ids.add(int(admin_id))
    except Exception:
        pass
    return ids


def _format_wait(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minutes, secs = divmod(seconds, 60)
    if minutes and secs:
        return f"{minutes} мин {secs} сек"
    if minutes:
        return f"{minutes} мин"
    return f"{secs} сек"


def _nudge_text(decision: SpamDecision) -> str:
    """The friendly "не торопись" message, in the bot's voice."""
    wait = _format_wait(decision.retry_after)
    if decision.reason == "flood":
        return (
            "⏳ <b>Не торопись!</b>\n"
            f"Слишком много команд подряд — подожди {wait}."
        )
    action = decision.action.label if decision.action else "эту кнопку"
    return (
        "⏳ <b>Не торопись!</b>\n"
        f"Только что нажал «{action}» — подожди {wait}."
    )


async def _send_nudge(update, context, decision: SpamDecision) -> None:
    text = _nudge_text(decision)
    try:
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text(text, parse_mode="HTML")
            return
        chat = getattr(update, "effective_chat", None)
        if chat is not None:
            await context.bot.send_message(chat_id=chat.id, text=text, parse_mode="HTML")
    except Exception as exc:
        logger.debug(f"antispam: nudge was not delivered: {exc}")


async def _delete_user_message(update) -> None:
    """Remove the spam message itself so the chat stays clean."""
    try:
        chat = getattr(update, "effective_chat", None)
        if chat is None or getattr(chat, "type", "") not in ("group", "supergroup", "channel"):
            return
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.delete()
    except Exception as exc:
        logger.debug(f"antispam: spam message was not deleted: {exc}")


async def guard_handler(update, context) -> None:
    """
    PTB handler that stops a repeated action before it reaches the bot logic.

    Install it in a group *before* the command handlers, e.g.::

        app.add_handler(MessageHandler(filters.ALL, antispam.guard_handler), group=-2)
        app.add_handler(CallbackQueryHandler(antispam.guard_handler), group=-2)

    Raising :class:`ApplicationHandlerStop` cancels every other handler, so
    the repeated action is neither executed nor answered twice — the user
    only gets a friendly "не торопись" instead.
    """
    decision = check_update(update)
    if decision is None or decision.allowed:
        return

    action = decision.action
    logger.info(
        f"antispam: {decision.reason} for user={getattr(update.effective_user, 'id', None)} "
        f"action={action.key if action else '?'} wait={decision.retry_after:.0f}s"
    )
    if decision.warn:
        await _send_nudge(update, context, decision)
    await _delete_user_message(update)
    raise ApplicationHandlerStop


def reset_state(user_id: int | None = None) -> None:
    """Test helper: forget the anti-spam state."""
    spam_guard.reset(user_id)
