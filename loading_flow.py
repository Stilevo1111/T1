"""Unified animated loading flow.

A single message is sent, "types" the label, then keeps a spinner running while
the real work happens. Callers later edit that same message into the result, so
no extra chat messages are produced.

For results that are pictures, `show_photo_with_typing` posts the picture
first and types the caption underneath it in the background, so the caller can
return immediately and finish its database work without waiting.

Usage:
    handle = await show_loading(bot, chat_id)
    try:
        ...work...
    finally:
        await stop_loading(handle)          # or stop_loading_by_id(...)
    await bot.edit_message_text(chat_id=chat_id, message_id=handle.message_id, ...)
"""
import asyncio
import html
import logging
import re

logger = logging.getLogger(__name__)

TYPED_LABEL = "Хукаю..."
LOADING_ICON = "🪝 "

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
_typing_tasks: set = set()


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
            if any(marker in msg for marker in _GONE_MARKERS):
                logger.debug(f"loading_flow: message {message_id} is gone ({name})")
                return False
            logger.debug(f"loading_flow: edit failed ({name}: {e})")
            return True


def _chunk_for(label: str) -> int:
    """Characters revealed per frame for this label."""
    return TYPE_CHUNK_SHORT if len(label) <= SHORT_LABEL_CHARS else TYPE_CHUNK_LONG


async def _type_label(
    bot, chat_id: int, message_id: int, label: str, icon: str
) -> None:
    """Type the label out, then leave the finished text in place.

    The icon is prepended as a whole and never typed: emoji are surrogate pairs
    in Python strings, so slicing them per frame could split a glyph in half.
    The first chunk is skipped because it is what send_message already showed,
    and re-editing identical text makes Telegram answer "message is not
    modified".
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    chunk = _chunk_for(label)

    for end in range(chunk * 2, len(label) + chunk, chunk):
        if asyncio.current_task().cancelling():
            return
        if not await _edit(bot, chat_id, message_id, f"<b>{icon}{label[:end]}</b>"):
            return
        if loop.time() - started > MAX_EDIT_SECONDS:
            return
        await asyncio.sleep(TYPE_INTERVAL)


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


async def show_photo_with_typing(
    bot,
    chat_id: int,
    media,
    caption: str,
    parse_mode: str = "HTML",
    reply_markup=None,
    label: str = "",
):
    """Post the picture first, then type the caption underneath it.

    The roll used to appear as a picture with its full caption at once. Here
    the picture shows up right away and the caption is typed out character by
    character, so the result reads as it is being written. A non-empty `label`
    is the caption until typing starts.

    The typing runs as a background task and this function returns as soon as
    the picture is posted. That matters for the roll: it still has to write the
    fissure to the database and set the cooldown, and those must not wait three
    seconds for an animation - or be lost if the handler is cancelled.

    Returns the Message, or None when the picture could not be sent.
    """
    first = f"<b>{label}</b>" if label else "…"
    try:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=media,
            caption=first,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.debug(f"loading_flow: could not send picture: {e}")
        return None

    _spawn_typing(bot, chat_id, msg.message_id, caption, parse_mode)
    return msg


def _spawn_typing(bot, chat_id: int, message_id: int, caption: str, parse_mode: str):
    """Run the caption animation in the background, keeping a strong reference.

    asyncio only holds weak references to tasks, so without this a typing task
    can be garbage collected mid-animation and the caption would stop halfway.
    """
    task = asyncio.create_task(_type_caption(bot, chat_id, message_id, caption, parse_mode))
    _typing_tasks.add(task)
    task.add_done_callback(_typing_tasks.discard)
    return task


_TAG_RE = re.compile(r"<[^>]+>")


def _safe_end(text: str, end: int) -> int:
    """Pull `end` back so a frame never ends on half of an emoji.

    Python strings are code points, so slicing between the two halves of a
    surrogate pair produces a lone surrogate that Telegram rejects outright.
    """
    if 0 < end < len(text) and "\ud800" <= text[end - 1] <= "\udbff":
        return end - 1
    return end


def _plain_text(html_text: str) -> str:
    """The visible words of an HTML caption, with entities resolved.

    Intermediate frames are typed as plain text so a frame can never cut an
    HTML tag in half. The last frame replaces them with the real caption, so
    the user still ends up with the formatted version.
    """
    return html.unescape(_TAG_RE.sub("", html_text))


async def _type_caption(
    bot, chat_id: int, message_id: int, caption: str, parse_mode: str
) -> None:
    """Reveal the caption progressively under an already posted picture.

    Characters are revealed in chunks at TYPE_INTERVAL, so a ~60 character roll
    caption takes a few seconds to write out instead of appearing at once.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    plain = _plain_text(caption)
    chunk = _chunk_for(plain)
    lock = _lock_for(chat_id)

    async def put(text: str) -> bool:
        """Edit the caption; False means the message is unusable."""
        async with lock:
            try:
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    parse_mode=parse_mode,
                )
                return True
            except Exception as e:
                name = type(e).__name__
                msg = str(e).lower()
                if "not modified" in msg:
                    return True
                if any(marker in msg for marker in _GONE_MARKERS):
                    logger.debug(
                        f"loading_flow: caption target {message_id} is gone ({name})"
                    )
                    return False
                logger.debug(f"loading_flow: caption edit failed ({name}: {e})")
                return False

    for end in range(chunk, len(plain), chunk):
        if asyncio.current_task().cancelling():
            return
        if not await put(plain[:_safe_end(plain, end)]):
            return
        if loop.time() - started > MAX_EDIT_SECONDS:
            # Out of time: put the whole formatted caption in place at once.
            await put(caption)
            return
        await asyncio.sleep(TYPE_INTERVAL)

    # Last frame is the real caption, so the result keeps its formatting.
    if not await put(caption):
        return
    if loop.time() - started > MAX_EDIT_SECONDS:
        logger.debug("loading_flow: caption typing hit the time limit")


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
