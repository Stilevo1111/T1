# -*- coding: utf-8 -*-
"""
Утилиты для бота: кэширование, история действий, напоминания, статистика
"""
import time
import logging
import asyncio
from functools import wraps
from typing import Any, Callable, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================
# 1. КЭШИРОВАНИЕ ФУНКЦИЙ (декоратор)
# ============================================================

class FunctionCache:
    """Простой кэш для результатов функций с TTL"""
    
    def __init__(self, default_ttl=300):
        self._cache = {}
        self.default_ttl = default_ttl
    
    def get(self, key: str) -> tuple[Any, bool]:
        """Вернуть (значение, найдено ли)"""
        if key in self._cache:
            value, expiry = self._cache[key]
            if time.time() < expiry:
                return value, True
            else:
                del self._cache[key]
        return None, False
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        ttl = ttl or self.default_ttl
        self._cache[key] = (value, time.time() + ttl)
    
    def delete(self, key: str):
        self._cache.pop(key, None)
    
    def clear(self):
        self._cache.clear()


function_cache = FunctionCache(default_ttl=600)


def cached(ttl: int = 600, key_builder: Optional[Callable] = None):
    """
    Декоратор для кэширования результатов функции
    
    Пример использования:
        @cached(ttl=300)  # 5 минут
        def get_exchange_rate():
            return requests.get(...).json()
        
        @cached(ttl=60, key_builder=lambda x, y: f"{x}_{y}")
        def get_user_stats(user_id, stat_type):
            return db.query(...)
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Строим ключ кэша
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                cache_key = f"{func.__module__}.{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Пробуем получить из кэша
            cached_value, found = function_cache.get(cache_key)
            if found:
                logger.debug(f"Cache hit: {cache_key}")
                return cached_value
            
            # Выполняем функцию
            result = func(*args, **kwargs)
            function_cache.set(cache_key, result, ttl)
            logger.debug(f"Cache set: {cache_key} (ttl={ttl}s)")
            return result
        
        # Методы для управления кэшем
        wrapper.cache = function_cache
        wrapper.cache_clear = lambda: function_cache.clear()
        return wrapper
    return decorator


# ============================================================
# 2. ИСТОРИЯ ДЕЙСТВИЙ ПОЛЬЗОВАТЕЛЯ
# ============================================================

class ActionHistory:
    """Простая история действий пользователя в памяти"""
    
    def __init__(self, max_per_user=50):
        self._history = {}  # telegram_id -> [(timestamp, action, details)]
        self._max_per_user = max_per_user
    
    def add(self, telegram_id: int, action: str, details: str = ""):
        if telegram_id not in self._history:
            self._history[telegram_id] = []
        
        self._history[telegram_id].append((time.time(), action, details))
        
        # Ограничиваем размер
        if len(self._history[telegram_id]) > self._max_per_user:
            self._history[telegram_id] = self._history[telegram_id][-self._max_per_user:]
    
    def get_recent(self, telegram_id: int, limit: int = 10):
        if telegram_id not in self._history:
            return []
        return self._history[telegram_id][-limit:]
    
    def get_today(self, telegram_id: int):
        if telegram_id not in self._history:
            return []
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return [(ts, action, details) for ts, action, details in self._history[telegram_id] if ts >= today_start]
    
    def get_all_users(self):
        return list(self._history.keys())


action_history = ActionHistory(max_per_user=100)


def log_user_action(telegram_id: int, action: str, details: str = ""):
    """Записать действие пользователя в историю"""
    action_history.add(telegram_id, action, details)


def get_user_action_count_today(telegram_id: int) -> int:
    """Сколько действий пользователь совершил сегодня"""
    return len(action_history.get_today(telegram_id))


# ============================================================
# 3. ОТЛОЖЕННЫЕ НАПОМИНАНИЯ
# ============================================================

class ReminderManager:
    """Менеджер напоминаний"""
    
    def __init__(self):
        self._reminders = {}  # (chat_id, user_id) -> (timestamp, message)
        self._job_queue = None
    
    def set_job_queue(self, job_queue):
        self._job_queue = job_queue
    
    def add(self, chat_id: int, user_id: int, delay_seconds: int, message: str):
        """Добавить напоминание через delay_seconds"""
        key = (chat_id, user_id)
        
        if self._job_queue:
            self._job_queue.run_once(
                reminder_job,
                delay_seconds,
                data={
                    'chat_id': chat_id,
                    'user_id': user_id,
                    'message': message
                },
                name=f"reminder_{chat_id}_{user_id}_{int(time.time())}"
            )
        else:
            # Fallback: сохраняем в память (менее надежно при перезапуске)
            self._reminders[key] = (time.time() + delay_seconds, message)
    
    def get_pending(self, chat_id: int, user_id: int):
        key = (chat_id, user_id)
        if key in self._reminders:
            expiry, message = self._reminders[key]
            if time.time() < expiry:
                return message
            else:
                del self._reminders[key]
        return None


reminder_manager = ReminderManager()


async def reminder_job(context):
    """Job для отправки напоминания"""
    try:
        bot = context.application.bot
        chat_id = context.job.data['chat_id']
        user_id = context.job.data['user_id']
        message = context.job.data['message']
        
        await bot.send_message(chat_id=chat_id, text=f"🔔 Напоминание: {message}")
        logger.info(f"Напоминание отправлено пользователю {user_id} в чате {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка в reminder_job: {e}")


def parse_reminder(text: str) -> tuple[bool, int, str]:
    """
    Парсит текст типа "напомни через 10 минут купить молоко"
    Возвращает (успех, секунды, сообщение)
    
    Поддерживает:
    - "напомни через N минут/час/день ..."
    - "напомни через Nмин/мин/ч/час/д/день ..."
    """
    text_lower = text.lower().strip()
    
    if not text_lower.startswith("напомни"):
        return False, 0, ""
    
    # Убираем "напомни"
    remainder = text_lower[7:].strip()
    
    if not remainder.startswith("через"):
        return False, 0, ""
    
    remainder = remainder[5:].strip()
    
    import re
    match = re.match(r'(\d+)\s*(мин|минут|минуты|час|часа|часов|ч|д|день|дней|дня)', remainder)
    
    if not match:
        return False, 0, ""
    
    number = int(match.group(1))
    unit = match.group(2)
    
    # Вычисляем секунды
    if unit in ('мин', 'минут', 'минуты', 'мин'):
        seconds = number * 60
    elif unit in ('час', 'часа', 'часов', 'ч'):
        seconds = number * 3600
    elif unit in ('д', 'день', 'дней', 'дня'):
        seconds = number * 86400
    else:
        return False, 0, ""
    
    # Получаем текст напоминания (оригинальный текст)
    # Находим позицию после числового значения
    msg_start = text.find(match.group(0))
    if msg_start == -1:
        return False, 0, ""
    
    reminder_text = text[msg_start + len(match.group(0)):].strip()
    if not reminder_text:
        reminder_text = "Напоминание"
    
    return True, seconds, reminder_text


# ============================================================
# 4. СТАТИСТИКА ИСПОЛЬЗОВАНИЯ
# ============================================================

class UsageStats:
    """Простая статистика использования бота"""
    
    def __init__(self):
        self._stats = {
            'total_commands': 0,
            'unique_users_today': set(),
            'unique_users_all': set(),
            'commands_today': {},
            'start_date': datetime.now().date()
        }
    
    def record_command(self, telegram_id: int, command: str):
        self._stats['total_commands'] += 1
        self._stats['unique_users_today'].add(telegram_id)
        self._stats['unique_users_all'].add(telegram_id)
        self._stats['commands_today'][command] = self._stats['commands_today'].get(command, 0) + 1
    
    def get_today_count(self) -> int:
        return len(self._stats['unique_users_today'])
    
    def get_total_count(self) -> int:
        return len(self._stats['unique_users_all'])
    
    def get_command_stats_today(self) -> dict:
        return dict(self._stats['commands_today'])
    
    def reset_daily(self):
        self._stats['unique_users_today'] = set()
        self._stats['commands_today'] = {}


usage_stats = UsageStats()


# ============================================================
# 5. ЧЁРНЫЙ СПИСОК (SPAM PROTECTION)
# ============================================================

class BlacklistManager:
    """Менеджер чёрного списка"""
    
    def __init__(self):
        self._blacklist = {}  # telegram_id -> (blocked_until, reason)
        self._auto_block_threshold = 5  # сообщений за короткое время
        self._auto_block_duration = 300  # 5 минут
    
    def is_blocked(self, telegram_id: int) -> bool:
        if telegram_id in self._blacklist:
            _, blocked_until = self._blacklist[telegram_id]
            if time.time() < blocked_until:
                return True
            else:
                del self._blacklist[telegram_id]
        return False
    
    def block(self, telegram_id: int, duration: int = 300, reason: str = "spamban"):
        """Заблокировать пользователя"""
        self._blacklist[telegram_id] = (time.time() + duration, reason)
    
    def unblock(self, telegram_id: int):
        """Разблокировать пользователя"""
        self._blacklist.pop(telegram_id, None)
    
    def get_reason(self, telegram_id: int) -> str:
        if telegram_id in self._blacklist:
            _, reason = self._blacklist[telegram_id]
            return reason
        return ""


blacklist = BlacklistManager()


# ============================================================
# 6. ПРИВЕТСТВИЕ НОВЫХ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================

WELCOME_MESSAGE = """
👋 Добро пожаловать!

Я бот для отслеживания активности в чате.

Команды:
• /help - Помощь
• /stats - Статистика бота

Наслаждайтесь! 🎮
"""

WELCOME_KEYBOARD = None  # Можно добавить клавиатуру при желании


async def send_welcome(bot, chat_id: int, user_id: int, username: str = ""):
    """Отправить приветствие новому пользователю"""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=f"👋 Привет, {username}!" if username else WELCOME_MESSAGE,
            reply_markup=WELCOME_KEYBOARD
        )
    except Exception as e:
        logger.error(f"Ошибка отправки приветствия: {e}")


# ============================================================
# ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ
# ============================================================

# Пример 1: Кэширование функции получения курса валют
"""
@cached(ttl=600)  # 10 минут
def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    # Реальный запрос к API
    response = requests.get(f"https://api.exchangerate.host/latest?base={from_currency}&symbols={to_currency}")
    return response.json()['rates'][to_currency]

# Использование:
rate = get_exchange_rate('USD', 'RUB')
"""

# Пример 2: Запись истории действий
"""
# В обработчике сообщений:
def handle_message(update, context):
    telegram_id = update.effective_user.id
    log_user_action(telegram_id, 'message', update.message.text[:50])
    
    # Проверка чёрного списка
    if blacklist.is_blocked(telegram_id):
        return  # Игнорируем
"""

# Пример 3: Напоминания
"""
def handle_reminder(update, context):
    text = update.message.text
    
    success, seconds, reminder_text = parse_reminder(text)
    if success:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        reminder_manager.add(chat_id, user_id, seconds, reminder_text)
        update.message.reply_text(f"✅ Напомню через {seconds//60} минут!")
"""

# Пример 4: Статистика
"""
def handle_stats(update, context):
    stats_text = f"""
📊 Статистика бота:
• Пользователей сегодня: {usage_stats.get_today_count()}
• Всего пользователей: {usage_stats.get_total_count()}
• Всего команд: {usage_stats._stats['total_commands']}
    """
    update.message.reply_text(stats_text)
"""