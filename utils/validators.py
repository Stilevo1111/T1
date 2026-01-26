"""Модуль для валидации данных"""

from typing import Optional, Union
import re

def validate_user_id(user_id: Union[str, int]) -> bool:
    """Валидация ID пользователя"""
    try:
        if isinstance(user_id, str):
            user_id = int(user_id)
        return user_id > 0
    except (ValueError, TypeError):
        return False

def validate_username(username: Optional[str]) -> str:
    """Валидация имени пользователя"""
    if not username:
        return "Unknown"
    # Ограничиваем длину имени
    return str(username)[:50]

def validate_item_name(item_name: Optional[str]) -> bool:
    """Валидация названия предмета"""
    if not item_name or not isinstance(item_name, str):
        return False
    # Проверяем, что имя не содержит опасных символов
    return bool(re.match(r'^[a-zA-Z0-9\s\-_]+$', item_name))

def validate_amount(amount: Union[str, int, float]) -> Optional[int]:
    """Валидация числового значения (золото, опыт и т.д.)"""
    try:
        if isinstance(amount, str):
            amount = float(amount)
        amount = int(amount)
        return amount if amount >= 0 else None
    except (ValueError, TypeError):
        return None

def validate_level(level: Union[str, int]) -> Optional[int]:
    """Валидация уровня персонажа"""
    try:
        if isinstance(level, str):
            level = int(level)
        return level if 1 <= level <= 30 else None
    except (ValueError, TypeError):
        return None

def validate_stat_value(value: Union[str, int]) -> Optional[int]:
    """Валидация значения характеристики"""
    try:
        if isinstance(value, str):
            value = int(value)
        return value if 0 <= value <= 1000 else None
    except (ValueError, TypeError):
        return None

def validate_talent_id(talent_id: Optional[str]) -> bool:
    """Валидация ID таланта"""
    if not talent_id or not isinstance(talent_id, str):
        return False
    # Формат: буква + цифра (например, w1, r2, m3)
    return bool(re.match(r'^[wrmh]\d+$', talent_id))

def validate_command_args(args: list, min_args: int = 0, max_args: int = None) -> bool:
    """Валидация аргументов команды"""
    if len(args) < min_args:
        return False
    if max_args is not None and len(args) > max_args:
        return False
    return True

def sanitize_text(text: str) -> str:
    """Санитизация текста от опасных символов"""
    if not text:
        return ""
    # Удаляем потенциально опасные символы, оставляя только безопасные
    return re.sub(r'[^\w\s\-.,!?()]+', '', str(text))[:500]