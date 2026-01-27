def format_stats_text(user_data):
    """Форматирует текст статистики пользователя"""
    if not user_data:
        return "Статистика недоступна"
    
    # Пример форматирования статистики
    stats_text = f"""
📊 Статистика пользователя

Имя: {user_data.get('name', 'Не указано')}
Уровень: {user_data.get('level', 0)}
Опыт: {user_data.get('exp', 0)}
Здоровье: {user_data.get('hp', 0)}/{user_data.get('max_hp', 0)}
Урон: {user_data.get('damage', 0)}
Защита: {user_data.get('defense', 0)}
    """.strip()
    
    return stats_text