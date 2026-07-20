# AGENTS.md — Руководство для ИИ-агента (Fissure Bot)

Этот файл — «карта» проекта для быстрой навигации. Читай его первым, прежде чем
править код. Цель: минимизировать поиск и избежать поломки связей между модулями.

## Что это за проект
Telegram-бот «Фиссура» на **Python 3.11** + **python-telegram-bot v21.7**.
Сочетает ролевую игру (рост/падение «фиссуры») с интеграцией Dota 2 (OpenDota API).
Работает в режиме **webhook** на Render.com. БД — **PostgreSQL** (Neon) с fallback на **SQLite**.
Кэш — **Redis** (с in-memory fallback). Подробности по командам — в `README.md`.

## Точка входа
- `main.py` — **главный файл**. Точка входа, регистрация всех хендлеров (`setup_application` ок. строки 3700), фоновые job'ы (приветствия, обновление MMR, дайджесты, weekly-лидерство), а также часть логики команд, ещё не вынесенной в модули.
- Запуск: `python main.py`. Хелсчек Render: `health_check()` в `main.py`.

## Карта модулей (что где лежит)
| Файл | Назначение |
|------|------------|
| `main.py` | Точка входа, регистрация хендлеров, фоновые задания, приветствия, leader election |
| `database.py` | **Самый важный модуль.** Все БД-операции, `User` dataclass, пул соединений, кэши (`user_cache`, `top_cache`), миграции, `get_connection/release_connection` |
| `config.py` | Pydantic-настройки из `.env` (BOT_TOKEN, DATABASE_URL, лимиты, rate-limit) |
| `constants.py` | Глобальные константы: кулдаун, баннеры (`get_banner_path`), таймауты, weekend-бонусы, фразы дайджеста |
| `rolls.py` | **Чистая логика фиссуры**: `calculate_fissure_roll`, `apply_fissure_protection`, `calculate_new_fissure`, `get_roll_text`, константы текстов |
| `fissure.py` | Обработка команды `/fissure` (кулдаун 24ч, мультикаст, анимации костей) — вынесено из `main.py` |
| `stats.py` | Шансы событий (multicast/zeus/techies) и TTL-константы заданий |
| `bot_utils.py` | Утилиты: `make_clickable` (HTML-ссылки), трекинг сообщений бота (`set_last_bot_message`), `bot_can_delete`, `main_menu`, `record_recent_fissure_roll` |
| `dota_mmr.py` | **Dota 2 / OpenDota**: `update_user_mmr`, `get_player_stats`, генерация карточек (`generate_start_card`), ранги, герои, аватары (~2050 строк) |
| `hero_meta.py` | Мета-герои по ролям (CARRY/MID/OFFLANE/SUPPORT), генерация картинок мета, circuit breaker для API |
| `hero_positions.py` | Статическая таблица позиций героев (POS 1-5) |
| `weekly_analytics.py` | `generate_weekly_analytics` — график импакта за 10 матчей, сравнение с про, чарты (~1629 строк) |
| `digest.py` | Дайджесты (лидерство, пин, кэш), `_DigestState` для multi-instance безопасности (~1067 строк) |
| `techies.py` | Мини-игра «Техиес» (мины, случайный взрыв фиссуры) |
| `mute.py` | Модерация: `/mute` (кляп за 10 см фиссуры). `register_handlers()` подключается в `main.py` |
| `events.py` | Простой in-memory `EventBus` (слабая связанность, используется ограниченно) |
| `cache.py` | `RedisCache` с fallback на in-memory |
| `rate_limiter.py` | Защита от Telegram API rate-limit: `rate_limit` декоратор, `is_rate_limited`, `set_rate_limited` |
| `analytics_dashboard.py` | Учёт ресурсов (OpenDota токены, Neon часы) |
| `container.py` | DI-контейнер (dependency_injector): `Container`, `UserRepository`. Примечание: НЕ используется активно в `main.py` |
| `demo_rolls.py` | Вспомогательный скрипт для демонстрации текстов роллов (не часть бота) |

## Индекс команд (команда → где смотреть)
Регистрация всех хендлеров — в `main.py` (~строки 3704-3721):

| Команда | Функция | Модуль / примечание |
|---------|---------|---------------------|
| `/start` | `start` | `main.py` |
| `/about` | `about` | `main.py` |
| `/fissure`, `/fissura` | `fissure` | `fissure.py` |
| `/profile` | `stats` | `main.py` + `dota_mmr.py` |
| `/info` | `info` | `main.py` |
| `/top` | `top` | `main.py` (топ фиссур) |
| `/topmmr` | `topmmr` | `main.py` (топ MMR) |
| `/refreshmmr` | `refreshmmr` | `main.py` |
| `/link` | `link` | `main.py` (привязка Steam) |
| `/digestnow`, `/dotadigestnow`, `/setdigestchat` | `digest_handler` | `digest.py` |
| `/resetgame` | `reset_game` | `main.py` + `database.reset_all_fissure_data` |
| `/analyze` | `analyze_command` | `main.py` + `weekly_analytics.py` |
| `/mute` | (в `mute.py`) | `mute.register_handlers()` |
| `/testgreeting`, `/testmvp`, `/testtechies` | тестовые | `main.py` / `mute` |

Кнопки inline-меню обрабатываются в `button_callback` (`main.py`), текст без команды — `menu_handler` (`main.py`).

## Фоновые задания (JobQueue) — `main.py`
- Утреннее/вечернее приветствие (09:00 / 23:00 МСК) — `morning_greeting_job` / `night_greeting_job`
- Обновление MMR всех пользователей (ежечасно) — `update_all_mmr_job` (только лидер)
- Чемпион недели (Вс 23:30) — `weekly_champion_announcement_job` → `announce_weekly_mmr_winner`
- Сброс недельной MMR-статистики (Пн 00:00) — `weekly_mmr_reset_job`
- Уменьшение фиссуры неактивным (раз в сутки) — `decrease_inactive_job`
- Очистка вышедших из чата — `cleanup_left_users_job`, `verify_chat_membership_job`
- Сброс кэша в БД — `flush_users_cache_job`

## Важные паттерны и правила
1. **Лидерство на Render (multi-instance).** Тяжёлые задания (`update_all_mmr_job`, weekly-задания) защищены `claim_or_check_mmr_leader()` / `claim_or_check_weekly_leader()` через `set_config` в БД. Не убирай эти проверки — иначе дубли на нескольких инстансах.
2. **Кэширование.** Данные пользователя кэшируются в `database.user_cache` / `top_cache`. После массовых апдейтов вызывай `flush_users_cache()` и инвалидируй кэш.
3. **Таймауты внешних API.** Все вызовы OpenDota обёрнуты в `aiohttp.ClientTimeout`. Не убирай таймауты — было зависание `/profile`.
4. **Rate-limit Telegram.** Публичные хендлеры обычно помечены `@rate_limit(tokens=1)`. `set_rate_limited` вызывается при 429.
5. **Генерация картинок** — Pillow, синхронная тяжёлая работа запускается через `asyncio.to_thread(...)`.
6. **Баннеры/картинки** — пути через `constants.get_banner_path(name)`, файлы в `assets/`, `images/`.
7. **Не изменяй тексты и визуал** без явной просьбы — многие модули помечены «извлечено из main.py без изменения поведения».

## Переменные окружения (`.env`)
`BOT_TOKEN`, `DATABASE_URL`, `REDIS_URL`, `ALLOWED_CHAT_ID`/`ALLOWED_CHATS`,
`MMR_CONCURRENCY_LIMIT` (лимит параллельных запросов к OpenDota, деф. 2),
`OPENAI_API_KEY`, `ADMIN_CHAT_ID`. Шаблон — `.env.example`.

## Как искать конкретное
- **Логика ролла фиссуры** → `rolls.py` (чистые функции) + `fissure.py` (обвязка команды).
- **Профиль/стата пользователя** → `database.get_user`, `main.py:stats`, `dota_mmr.update_user_mmr`.
- **Топы** → `database.get_fissure_top` / `get_dota_week_top`, функции `top`/`topmmr` в `main.py`.
- **Дайджест** → `digest.py` (+ `_ensure_pinned`, `_DigestState`).
- **Картинки/карточки** → `dota_mmr.generate_start_card`, `hero_meta`, `weekly_analytics.generate_weekly_analytics`.
- **БД-схема/миграции** → `database.py` (`init_db`, `migrate_db`, dataclass `User`).
- **Кэш/производительность** → `cache.py`, `database.user_cache`, `analytics_dashboard.py`.

## Тестирование
- Юнит-тесты в `tests/`. Запуск: `pytest` (конфиги в `pyproject.toml`, `requirements-dev.txt`).
- Быстрые проверки текстов роллов: `python demo_rolls.py`.
- Линтер: `ruff` (`.ruff_cache` присутствует).

## Стек / зависимости
Python 3.11.4, python-telegram-bot 21.7, psycopg2, aiohttp, redis.asyncio, Pillow,
structlog, pydantic-settings, dependency-injector (опц.), prometheus-client (опц.),
pytest (dev). Полный список — `requirements.txt` / `requirements-dev.txt`.
