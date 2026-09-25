"""Unified animated loading flow.

A single message is sent, "types" the label, then keeps a spinner running while
the real work happens. Callers later edit that same message into the result, so
no extra chat messages are produced.

Usage:
    handle = await show_loading(bot, chat_id)
    try:
        ...work...
    finally:
        await stop_loading(handle)          # or stop_loading_by_id(...)
    await bot.edit_message_text(chat_id=chat_id, message_id=handle.message_id, ...)
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

TYPED_LABEL = "Хукаю..."
CURSOR = "▌"
FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

TYPE_CHUNK = 2
TYPE_INTERVAL = 0.16
SPIN_INTERVAL = 0.45
MIN_EDIT_GAP = 0.12
MAX_EDIT_SECONDS = 12.0

_active: dict = {}
_chat_locks: dict = {}


class Loading:
    """Handle for an in-flight animated loading message."""

    def __init__(self, chat_id: int, message_id: int, task: asyncio.Task):
        self.chat_id = chat_id
        self.message_id = message_id
        self._task = task

    @property
    def stopped(self) -> bool:
        return self._task is None or self._task.done()

    def __bool__(self):
        return self.message_id != 0

    async def stop(self):
        await stop_loading(self)


def _lock_for(chat_id: int) -> asyncio.Lock:
    lock = _chat_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _chat_locks[chat_id] = lock
    return lock


async def _edit(bot, chat_id: int, message_id: int, text: str) -> bool:
    """Edit the message, throttled per chat. Returns False if the message is gone."""
    lock = _lock_for(chat_id)
    async with lock:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML"
            )
            return True
        except Exception as e:
            name = type(e).__name__
            msg = str(e).lower()
            if "not modified" in msg:
                return True
            if "message to edit not found" in msg or "message can't be deleted" in msg:
                logger.debug(f"loading_flow: message {message_id} is gone ({name})")
                return False
            logger.debug(f"loading_flow: edit failed ({name}: {e})")
            return True


async def _type_then_spin(bot, chat_id: int, message_id: int, label: str) -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()

    # Phase 1: type the label, TYPE_CHUNK characters per frame.
    for end in range(TYPE_CHUNK, len(label) + TYPE_CHUNK, TYPE_CHUNK):
        if asyncio.current_task().cancelling():
            return
        if not await _edit(
            bot, chat_id, message_id, f"<b>{label[:end]}{CURSOR}</b>"
        ):
            return
        if loop.time() - started > MAX_EDIT_SECONDS:
            return
        await asyncio.sleep(TYPE_INTERVAL)

    # Phase 2: keep spinning until the caller stops us.
    i = 0
    while True:
        if asyncio.current_task().cancelling():
            return
        if not await _edit(
            bot, chat_id, message_id, f"<b>{FRAMES[i % len(FRAMES)]} {label}</b>"
        ):
            return
        i += 1
        if loop.time() - started > MAX_EDIT_SECONDS:
            return
        await asyncio.sleep(SPIN_INTERVAL)


async def show_loading(bot, chat_id: int, label: str = TYPED_LABEL) -> Loading:
    """Send the loading message and start the animation."""
    try:
        msg = await bot.send_message(
            chat_id=chat_id, text=f"<b>{label[:1]}{CURSOR}</b>", parse_mode="HTML"
        )
    except Exception as e:
        logger.debug(f"loading_flow: could not send loading message: {e}")
        return Loading(chat_id, 0, None)

    task = asyncio.create_task(_type_then_spin(bot, chat_id, msg.message_id, label))
    handle = Loading(chat_id, msg.message_id, task)
    _active[(chat_id, msg.message_id)] = handle
    return handle


async def stop_loading(handle) -> None:
    """Stop the animation, if the handle is still running."""
    if handle is None:
        return
    task = getattr(handle, "_task", None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    handle._task = None
    message_id = getattr(handle, "message_id", 0)
    chat_id = getattr(handle, "chat_id", None)
    if message_id and chat_id is not None:
        _active.pop((chat_id, message_id), None)


async def stop_loading_by_id(bot, chat_id: int, message_id: int) -> None:
    """Stop the animation for a message referenced only by id."""
    if not message_id:
        return
    handle = _active.pop((chat_id, message_id), None)
    if handle is not None:
        await stop_loading(handle)
        return
    # Not tracked (e.g. reloaded process): cancel by iterating live tasks.
    for (cid, mid), h in list(_active.items()):
        if cid == chat_id and mid == message_id:
            await stop_loading(h)
