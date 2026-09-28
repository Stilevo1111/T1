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
LOADING_ICON = "🪝 "
SPINNER_FRAMES = ["🪝", "🔄", "⏳", "🔄"]
SPINNER_INTERVAL = 0.5

# Short labels ("Хукаю...") are typed one character at a time, which reads as
# real typing. Longer ones move two characters per frame: at one char per frame
# a 25-character label would take four seconds of pure animation, which is
# worse than a slightly chunkier effect. Both stay far below Telegram's rate
# limits - a long label is ~13 edits in total.
SHORT_LABEL_CHARS = 12
TYPE_CHUNK_SHORT = 1
TYPE_CHUNK_LONG = 2
TYPE_INTERVAL = 0.11
MIN_EDIT_GAP = 0.12
MAX_EDIT_SECONDS = 12.0

# Error fragments that mean "this message can no longer be edited". Telegram
# words them differently depending on the reason it became uneditable, and a
# deleted message must stop the animation instead of raising every tick.
_GONE_MARKERS = (
    "message to edit not found",
    "message can't be edited",
    "message can't be deleted",
    "message to delete not found",
    "message identifier is not specified",
    "message is not modified",
)

_active: dict = {}
_chat_locks: dict = {}
_last_edit_time: dict = {}


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
    """Edit the message, throttled per chat. Returns False if it is gone."""
    lock = _lock_for(chat_id)
    async with lock:
        last_edit = _last_edit_time.get(chat_id, 0)
        now = asyncio.get_running_loop().time()
        gap = now - last_edit
        if gap < MIN_EDIT_GAP:
            await asyncio.sleep(MIN_EDIT_GAP - gap)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML"
            )
            _last_edit_time[chat_id] = asyncio.get_running_loop().time()
            return True
        except Exception as e:
            name = type(e).__name__
            msg = str(e).lower()
            if "not modified" in msg:
                _last_edit_time[chat_id] = asyncio.get_running_loop().time()
                return True
            if any(marker in msg for marker in _GONE_MARKERS):
                logger.debug(f"loading_flow: message {message_id} is gone ({name})")
                return False
            logger.debug(f"loading_flow: edit failed ({name}: {e})")
            _last_edit_time[chat_id] = asyncio.get_running_loop().time()
            return True


def _chunk_for(label: str) -> int:
    """Characters revealed per frame for this label."""
    return TYPE_CHUNK_SHORT if len(label) <= SHORT_LABEL_CHARS else TYPE_CHUNK_LONG


async def _spinner_loop(
    bot, chat_id: int, message_id: int, label: str, icon: str, last_text: str = ""
) -> None:
    """Cycle the icon emoji to show the process is still alive after typing."""
    frame_idx = 0
    while True:
        if asyncio.current_task().cancelling():
            return
        frame = SPINNER_FRAMES[frame_idx % len(SPINNER_FRAMES)]
        text = f"<b>{frame} {label}</b>"
        if text == last_text:
            frame_idx += 1
            continue
        if not await _edit(bot, chat_id, message_id, text):
            return
        last_text = text
        frame_idx += 1
        await asyncio.sleep(SPINNER_INTERVAL)


async def _type_label(
    bot, chat_id: int, message_id: int, label: str, icon: str
) -> None:
    """Type the label out, then keep a spinner running until cancelled.

    The icon is prepended as a whole and never typed: emoji may be surrogate
    pairs in Python strings, so slicing them per frame could split a glyph.
    The first chunk is skipped because it is what send_message already showed,
    and re-editing identical text makes Telegram answer "message is not
    modified". After the label is fully typed, a spinner loop takes over
    to keep editing the icon and signal that the background work continues.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    chunk = _chunk_for(label)
    last_text = f"<b>{icon}{label}</b>"

    for end in range(chunk * 2, len(label) + chunk, chunk):
        if asyncio.current_task().cancelling():
            return
        last_text = f"<b>{icon}{label[:end]}</b>"
        if not await _edit(bot, chat_id, message_id, last_text):
            return
        if loop.time() - started > MAX_EDIT_SECONDS:
            break
        await asyncio.sleep(TYPE_INTERVAL)

    await _spinner_loop(bot, chat_id, message_id, label, icon, last_text)


async def show_loading(
    bot,
    chat_id: int,
    label: str = TYPED_LABEL,
    icon: str = LOADING_ICON,
) -> Loading:
    """Send the loading message and type the label into it."""
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=f"<b>{icon}{label[:_chunk_for(label)]}</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.debug(f"loading_flow: could not send loading message: {e}")
        return Loading(chat_id, 0, None)

    task = asyncio.create_task(_type_label(bot, chat_id, msg.message_id, label, icon))
    handle = Loading(chat_id, msg.message_id, task)
    _active[(chat_id, msg.message_id)] = handle
    return handle


async def finish_loading(
    bot,
    handle,
    text: str,
    media=None,
    parse_mode: str = "HTML",
    reply_markup=None,
):
    """Turn the loading message into the result, in place.

    With `media` the message is converted to a photo and `text` becomes its
    caption, so the chat keeps a single message from loading to result. Returns
    the resulting Message, or None when the loading message cannot be reused -
    callers then fall back to sending a fresh message.
    """
    if not handle:
        return None
    message_id = getattr(handle, "message_id", 0)
    chat_id = getattr(handle, "chat_id", None)
    if not message_id or chat_id is None:
        return None

    await stop_loading(handle)

    if media is not None:
        try:
            from telegram import InputMediaPhoto
        except ImportError:  # pragma: no cover - telegram is a hard dependency
            return None
        try:
            result = await bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=InputMediaPhoto(media, caption=text, parse_mode=parse_mode),
            )
            if reply_markup is not None:
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_markup=reply_markup,
                    )
                except Exception as e:
                    logger.debug(f"loading_flow: reply markup failed: {e}")
            return result
        except Exception as e:
            logger.debug(f"loading_flow: cannot convert to media ({e})")
            return None

    try:
        return await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.debug(f"loading_flow: cannot finish with text ({e})")
        return None


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


async def delete_loading(bot, handle) -> None:
    """Stop the animation and remove the loading message.

    Always use this instead of calling bot.delete_message directly: the typing
    task would otherwise keep editing a message that no longer exists and
    Telegram would reject every following edit.
    """
    if not handle:
        return
    message_id = getattr(handle, "message_id", 0)
    chat_id = getattr(handle, "chat_id", None)
    if not message_id or chat_id is None:
        return
    await stop_loading(handle)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.debug(f"loading_flow: delete failed for {message_id}: {e}")
