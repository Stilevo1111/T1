# Анализ обращений к базе данных

## Обзор

Код использует **систему кеширования** для оптимизации обращений к БД. Многие функции сначала проверяют кеш, и только при отсутствии данных обращаются к БД.

## Функции с кешем (обращаются к БД только при промахе кеша)

### 1. `get_user(telegram_id, username=None)`
- **Кеш**: Да (проверяет `user_cache.get(telegram_id)`)
- **Запрос к БД**: SELECT * FROM users WHERE telegram_id = ?
- **Причина**: Получение данных пользователя
- **Когда обращается к БД**: Только при первом запросе или если пользователь не в кеше

### 2. `get_digest_stats()`
- **Кеш**: Да (проверяет `user_cache.get('digest_stats')`)
- **Запрос к БД**: Сложный SELECT с агрегацией данных пользователей
- **Причина**: Получение статистики для утреннего/вечернего дайджеста
- **Когда обращается к БД**: Только при первом запросе или после сброса кеша

### 3. `get_weekly_digest_stats()`
- **Кеш**: Да (проверяет `user_cache.get('weekly_digest_stats')`)
- **Запрос к БД**: Сложный SELECT с агрегацией данных пользователей
- **Причина**: Получение статистики для еженедельного дайджеста
- **Когда обращается к БД**: Только при первом запросе или после сброса кеша

### 4. `get_dota_digest_stats()`
- **Кеш**: Да (проверяет `user_cache.get('dota_digest_stats')`)
- **Запрос к БД**: Сложный SELECT с агрегацией данных пользователей
- **Причина**: Получение статистики для Dota дайджеста
- **Когда обращается к БД**: Только при первом запросе или после сброса кеша

## Функции с кешем (обращаются к БД только при промахе кеша) - ДОБАВЛЕНО

### 5. `get_config(key, default=None)`
- **Кеш**: Да (проверяет `config_cache.get(key)`)
- **TTL**: 5 минут (300 секунд)
- **Запрос к БД**: SELECT value FROM bot_config WHERE key = ?
- **Причина**: Получение значения конфигурации
- **Когда обращается к БД**: Только при первом запросе или после истечения TTL

### 6. `get_fissure_top(limit=10)`
- **Кеш**: Да (проверяет `top_cache.get(f'fissure_top_{limit}')`)
- **TTL**: 1 минута (60 секунд)
- **Запрос к БД**: SELECT telegram_id, username, fissure FROM users ORDER BY fissure DESC LIMIT ?
- **Причина**: Получение топа пользователей по fissure
- **Когда обращается к БД**: Только при первом запросе или после истечения TTL

### 7. `get_user_rank(telegram_id)`
- **Кеш**: Да (проверяет `top_cache.get(f'user_rank_{telegram_id}')`)
- **TTL**: 1 минута (60 секунд)
- **Запрос к БД**: SELECT COUNT(*) + 1 as rank FROM users WHERE mmr > (SELECT mmr FROM users WHERE telegram_id = ?) AND steam_id IS NOT NULL
- **Причина**: Получение позиции игрока в топе по MMR
- **Когда обращается к БД**: Только при первом запросе или после истечения TTL

### 8. `get_fissure_rank(telegram_id)`
- **Кеш**: Да (проверяет `top_cache.get(f'fissure_rank_{telegram_id}')`)
- **TTL**: 1 минута (60 секунд)
- **Запрос к БД**: SELECT COUNT(*) + 1 as rank FROM users WHERE fissure > (SELECT fissure FROM users WHERE telegram_id = ?)
- **Причина**: Получение позиции игрока в топе по fissure
- **Когда обращается к БД**: Только при первом запросе или после истечения TTL

## Функции без кеша (всегда обращаются к БД)

### 9. `update_fissure(telegram_id, fissure, last_fissure, growth=0)`
- **Кеш**: Нет (пишет в кеш, но не читает из него)
- **Запрос к БД**: UPDATE users SET fissure=?, last_fissure=?, ...
- **Причина**: Обновление данных fissure пользователя
- **Примечание**: Пишет в кеш и помечает как dirty, но не читает из кеша

### 10. `update_last_message_id(telegram_id, message_id)`
- **Кеш**: Нет
- **Запрос к БД**: UPDATE users SET last_message_id=? WHERE telegram_id=?
- **Причина**: Обновление ID последнего сообщения пользователя

### 11. `decrease_inactive_fissure(days_inactive=1, decrease_amount=1.0)`
- **Кеш**: Нет
- **Запрос к БД**: UPDATE users SET fissure = GREATEST(0.1, fissure - ?) WHERE last_activity < CURRENT_TIMESTAMP - INTERVAL '? days' AND fissure > 0.1
- **Причина**: Уменьшение fissure для неактивных игроков (ежедневная задача)

### 12. `get_config(key, default=None)`
- **Кеш**: Нет
- **Запрос к БД**: SELECT value FROM bot_config WHERE key = ?
- **Причина**: Получение значения конфигурации

### 13. `set_config(key, value)`
- **Кеш**: Нет
- **Запрос к БД**: INSERT INTO bot_config (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = ?
- **Причина**: Установка значения конфигурации

### 14. `update_player_positions()`
- **Кеш**: Нет
- **Запрос к БД**: UPDATE users SET current_position = ..., previous_position = current_position
- **Причина**: Обновление позиций игроков (ежедневная задача)

### 15. `update_digest_snapshot()`
- **Кеш**: Нет
- **Запрос к БД**: UPDATE users SET digest_fissure = fissure, digest_position = current_position
- **Причина**: Обновление снимка для дайджеста

### 16. `update_weekly_digest_snapshot()`
- **Кеш**: Нет
- **Запрос к БД**: UPDATE users SET weekly_rolls = 0, weekly_growth = 0, ...
- **Причина**: Обновление снимка для еженедельного дайджеста и сброс недельных счётчиков

### 17. `init_db()`
- **Кеш**: Нет
- **Запрос к БД**: CREATE TABLE IF NOT EXISTS users (...), CREATE TABLE IF NOT EXISTS bot_config (...)
- **Причина**: Инициализация таблиц базы данных

### 18. `migrate_db()`
- **Кеш**: Нет
- **Запрос к БД**: ALTER TABLE users ADD COLUMN IF NOT EXISTS ...
- **Причина**: Миграция базы данных (добавление новых столбцов)

### 19. `get_connection()`
- **Кеш**: Нет (но использует пул соединений)
- **Запрос к БД**: Получение соединения из пула
- **Причина**: Получение соединения с базой данных

## Сценарии обращений к БД

### 1. Инициализация бота (при запуске)
- `init_db()` - 1 запрос (CREATE TABLE)
- `migrate_db()` - N запросов (ALTER TABLE для каждой миграции)
- **Итого**: 1 + N запросов

### 2. Ежедневная задача (decrease_inactive_job)
- `decrease_inactive_fissure()` - 1 запрос (UPDATE)
- `update_player_positions()` - 1 запрос (UPDATE)
- **Итого**: 2 запроса

### 3. Утренний дайджест (morning_digest_job) - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_config('digest_chat_id')` - 0 запросов (из кеша)
- `get_digest_stats()` - 0 запросов (из кеша)
- `get_config('daily_digest_message_id')` - 0 запросов (из кеша)
- `set_config('daily_digest_message_id', msg.message_id)` - 1 запрос (INSERT/UPDATE)
- `update_digest_snapshot()` - 1 запрос (UPDATE)
- **Итого**: 2 запроса (было 4-5)

### 4. Вечерний дайджест (evening_digest_job) - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_config('digest_chat_id')` - 0 запросов (из кеша)
- `get_digest_stats()` - 0 запросов (из кеша)
- `get_config('daily_digest_message_id')` - 0 запросов (из кеша)
- `set_config('daily_digest_message_id', None)` - 1 запрос (INSERT/UPDATE)
- **Итого**: 1 запрос (было 3-4)

### 5. Еженедельный дайджест (weekly_digest_job) - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_config('digest_chat_id')` - 0 запросов (из кеша)
- `get_weekly_digest_stats()` - 0 запросов (из кеша)
- `get_config('weekly_digest_message_id')` - 0 запросов (из кеша)
- `set_config('weekly_digest_message_id', msg.message_id)` - 1 запрос (INSERT/UPDATE)
- `update_weekly_digest_snapshot()` - 1 запрос (UPDATE)
- **Итого**: 2 запроса (было 4-5)

### 6. Dota дайджест (dota_digest_job) - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_config('digest_chat_id')` - 0 запросов (из кеша)
- `get_dota_digest_stats()` - 0 запросов (из кеша)
- `get_config('dota_digest_message_id')` - 0 запросов (из кеша)
- `set_config('dota_digest_message_id', msg.message_id)` - 1 запрос (INSERT/UPDATE)
- **Итого**: 1 запрос (было 3-4)

### 7. Alternate дайджест (alternate_digest_job) - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_config('digest_chat_id')` - 0 запросов (из кеша)
- `get_config('alternate_digest_type')` - 0 запросов (из кеша)
- `get_digest_stats()` или `get_dota_digest_stats()` - 0 запросов (из кеша)
- `get_config('alternate_digest_message_id')` - 0 запросов (из кеша)
- `set_config('alternate_digest_message_id', msg.message_id)` - 1 запрос (INSERT/UPDATE)
- `set_config('alternate_digest_type', next_type)` - 1 запрос (INSERT/UPDATE)
- **Итого**: 2 запроса (было 5-6)

### 8. Команда /fissure - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_user(user_obj.id, username)` - 0 запросов (из кеша)
- `update_fissure(user_obj.id, new_fissure, now, roll)` - 1 запрос (UPDATE)
- `update_last_message_id(user_obj.id, result_msg.message_id)` - 1 запрос (UPDATE)
- **Итого**: 2 запроса (было 2-3)

### 9. Команда /top - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_fissure_top(10)` - 0 запросов (из кеша)
- `get_fissure_rank(update.effective_user.id)` - 0 запросов (из кеша)
- `get_user(update.effective_user.id, update.effective_user.username)` - 0 запросов (из кеша)
- `update_last_message_id(update.effective_user.id, result_msg.message_id)` - 1 запрос (UPDATE)
- **Итого**: 1 запрос (было 3-4)

### 10. Команда /topmmr - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_user(update.effective_user.id)` - 0 запросов (из кеша)
- `update_user_mmr(update.effective_user.id)` - может обращаться к БД для обновления MMR
- `get_user(update.effective_user.id)` - 0 запросов (из кеша)
- `get_connection()` - получение соединения
- **Итого**: 0-1 запрос (было 2-3)

### 11. Команда /mmr - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_user(update.effective_user.id)` - 0 запросов (из кеша)
- **Итого**: 0 запросов (было 0-1)

### 12. Команда /start - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_user(uid, username)` - 0 запросов (из кеша)
- `update_last_message_id(uid, result_msg.message_id)` - 1 запрос (UPDATE)
- **Итого**: 1 запрос (было 1-2)

### 13. Команда /setdigest - ПОСЛЕ ОПТИМИЗАЦИИ
- `set_config("digest_chat_id", chat_id)` - 1 запрос (INSERT/UPDATE)
- `set_config("daily_digest_message_id", None)` - 1 запрос (INSERT/UPDATE)
- **Итого**: 2 запроса (без изменений)

### 14. Команда /setweeklydigest - ПОСЛЕ ОПТИМИЗАЦИИ
- `set_config("digest_chat_id", chat_id)` - 1 запрос (INSERT/UPDATE)
- `set_config("weekly_digest_message_id", None)` - 1 запрос (INSERT/UPDATE)
- **Итого**: 2 запроса (без изменений)

### 15. Автоматическая установка digest_chat_id - ПОСЛЕ ОПТИМИЗАЦИИ
- `get_config("digest_chat_id")` - 0 запросов (из кеша)
- `set_config("digest_chat_id", chat_id)` - 1 запрос (INSERT/UPDATE) если не был установлен
- **Итого**: 0-1 запрос (было 1-2)

## Статистика по типам запросов (ПОСЛЕ ОПТИМИЗАЦИИ)

### SELECT запросы (чтение данных) - ТЕПЕРЬ ИЗ КЕША
1. `get_user()` - получение данных пользователя (из кеша)
2. `get_fissure_top()` - получение топа пользователей (из кеша, TTL 1 минута)
3. `get_user_rank()` - получение ранга пользователя по MMR (из кеша, TTL 1 минута)
4. `get_fissure_rank()` - получение ранга пользователя по fissure (из кеша, TTL 1 минута)
5. `get_config()` - получение конфигурации (из кеша, TTL 5 минут)
6. `get_digest_stats()` - получение статистики для дайджеста (из кеша)
7. `get_weekly_digest_stats()` - получение недельной статистики (из кеша)
8. `get_dota_digest_stats()` - получение Dota статистики (из кеша)

### UPDATE запросы (обновление данных)
1. `update_fissure()` - обновление fissure пользователя
2. `update_last_message_id()` - обновление ID последнего сообщения
3. `decrease_inactive_fissure()` - уменьшение fissure для неактивных
4. `update_player_positions()` - обновление позиций игроков
5. `update_digest_snapshot()` - обновление снимка дайджеста
6. `update_weekly_digest_snapshot()` - обновление недельного снимка

### INSERT/UPDATE запросы (вставка или обновление)
1. `set_config()` - установка конфигурации

### CREATE TABLE запросы (создание таблиц)
1. `init_db()` - создание таблиц users и bot_config

### ALTER TABLE запросы (изменение структуры таблиц)
1. `migrate_db()` - добавление новых столбцов

## Оптимизации кеширования

### Что кешируется:
1. Данные пользователей (`user_cache`) - без TTL, сбрасывается при flush
2. Статистика дайджестов (`digest_stats`, `weekly_digest_stats`, `dota_digest_stats`) - без TTL, сбрасывается при обновлении
3. Конфигурация (`config_cache`) - TTL 5 минут, сбрасывается при изменении
4. Топ пользователей и ранги (`top_cache`) - TTL 1 минута, сбрасывается при изменении данных пользователей

### Что НЕ кешируется:
1. Позиции игроков (`update_player_positions`) - всегда обращается к БД
2. Обновления данных (`update_fissure`, `update_last_message_id`, `set_config`) - всегда обращаются к БД

## Реализованные оптимизации

### 1. Кеширование конфигурации ✅
- Добавлен кеш `config_cache` для `get_config()` с TTL 5 минут
- Кеш сбрасывается при вызове `set_config()`
- Это уменьшает количество запросов при частых вызовах `get_config()`

### 2. Кеширование топа пользователей ✅
- Добавлен кеш `top_cache` для `get_fissure_top()` с TTL 1 минута
- Кеш сбрасывается при обновлении данных пользователей
- Это уменьшает количество запросов при частых вызовах команды /top

### 3. Кеширование рангов пользователей ✅
- Добавлен кеш `top_cache` для `get_user_rank()` и `get_fissure_rank()` с TTL 1 минута
- Кеш сбрасывается при обновлении данных пользователей
- Это уменьшает количество запросов при частых вызовах команды /top

### 4. Батчинг обновлений
- Объединить несколько UPDATE запросов в один batch
- Например, обновлять `update_last_message_id()` вместе с `update_fissure()`

### 5. Асинхронные обновления
- Выполнять некритичные обновления асинхронно
- Например, `update_last_message_id()` можно выполнять в фоновом режиме

## Заключение

Код использует комплексную систему кеширования для оптимизации обращений к БД. Все основные оптимизации реализованы:
1. Кеширование данных пользователей (реализовано)
2. Кеширование статистики дайджестов (реализовано)
3. Кеширование конфигурации с TTL 5 минут (реализовано)
4. Кеширование топа и рангов с TTL 1 минута (реализовано)

Среднее количество обращений к БД за один цикл работы бота (ПОСЛЕ ОПТИМИЗАЦИИ):
- Инициализация: 1 + N запросов (без изменений)
- Ежедневные задачи: 2 запроса (без изменений)
- Дайджесты: 1-2 запроса каждый (было 3-6)
- Команды пользователей: 0-2 запроса каждая (было 1-4)

### Итоговая экономия запросов:
- Утренний дайджест: -60% запросов (с 4-5 до 2)
- Вечерний дайджест: -75% запросов (с 3-4 до 1)
- Еженедельный дайджест: -60% запросов (с 4-5 до 2)
- Dota дайджест: -75% запросов (с 3-4 до 1)
- Alternate дайджест: -67% запросов (с 5-6 до 2)
- Команда /fissure: -33% запросов (с 2-3 до 2)
- Команда /top: -75% запросов (с 3-4 до 1)
- Команда /topmmr: -67% запросов (с 2-3 до 0-1)
- Команда /mmr: -100% запросов (с 0-1 до 0)
- Команда /start: -50% запросов (с 1-2 до 1)
