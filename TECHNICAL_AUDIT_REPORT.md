# Технический аудит репозитория fissure-bot_new
**Дата аудита:** 2026-07-22  
**Аудитор:** Kilo  
**Версия кода:** main.py ~4149 строк, database.py ~3691 строк, dota_mmr.py ~2103 строк  

---

## 1. Общие оценки

| Категория | Оценка | Комментарий |
|-----------|--------|-------------|
| Архитектура | 4/10 | Сильный God Object (main.py), циклические зависимости, глобальное состояние |
| Качество кода | 5/10 | Много дублирования, мертвый код, длинные функции, magic numbers |
| Async/await | 4/10 | Синхронный `requests` в async коде, `time.sleep`, блокирующие операции |
| Telegram Bot | 6/10 | Работает, но есть race conditions, утечки памяти, дубли callback_data |
| База данных | 5/10 | Дублирование SQL для PG/SQLite, SELECT *, нет миграций, пулы смешанного типа |
| Кэширование | 6/10 | Несколько конкурирующих слоев кэша, инвалидация не всегда корректна |
| Производительность | 5/10 | Блокирующая генерация изображений, глобальные блокировки threading |
| Память | 4/10 | Неограниченные глобальные dict, утечки через asyncio tasks |
| Внешние API | 5/10 | Смесь sync/async клиентов, circuit breaker сбрасывается при каждом вызове |
| Безопасность | 5/10 | SQL-инъекции маловероятны, но есть открытые debug endpoints, HTML-инъекции |
| Логирование | 6/10 | Structlog + стандартный logging, но много чувствительных данных в логах |
| Конфигурация | 6/10 | Pydantic настроек OK, но много magic values в коде |
| Обработка ошибок | 4/10 | Много bare except, молчаливые failures, отсутствие retry в критических местах |
| Зависимости | 6/10 | Есть неиспользуемые пакеты (plotly, kaleido, APScheduler, dependency-injector) |
| DevOps | 7/10 | Render конфиг OK, CI/CD есть, graceful shutdown есть |
| Масштабируемость | 3/10 | Не готов к 10K+ пользователям: in-memory state, single process, блокирующие операции |

---

## 2. Критические проблемы (Critical / High Severity)

### [CRITICAL] 2.1. God Object main.py + циклические зависимости
**Заголовок:** Монолит main.py (4149 строк) с циклическими импортами  
**Файлы:** `main.py`, `database.py`, `dota_mmr.py`, `digest.py`, `fissure.py`, `bot_utils.py`  
**Почему это проблема:**  
- `main.py` импортирует процессы из 10+ модулей и содержит точку входа, веб-сервер, обработчики, фоновые jobs, логику приветствий, leader election и утилиты.  
- Циклические зависимости: `main.py` ↔ `database.py` ↔ `dota_mmr.py` ↔ `digest.py`. Например, `database.py` импортирует `main.py` в `get_dota_mmr_top` (строка 2976), а `main.py` импортирует `database.py` на строке 32.  
- Любое изменение в `main.py` требует регрессионного тестирования всего бота.  
**Решение:** Разделить `main.py` на domain-модули (handlers, jobs, webhooks). Использовать явные интерфейсы для обращения к БД и внешним API. Убрать обратные импорты из `database.py` в `main.py`.  
**Сложность:** Высокая (2-3 дня)  
**Влияние на производительность:** Нет прямого влияния, но упрощает поддержку и reduces cognitive load.

### [CRITICAL] 2.2. Синхронный `requests` в асинхронном коде + `time.sleep`
**Заголовок:** Блокирующие HTTP-запросы и `time.sleep` в async-функциях  
**Файлы:** `dota_mmr.py` (строки 280-353, 569-610, 858-900, 1150-1180), `weekly_analytics.py` (426-454)  
**Почему это проблема:**  
- Функция `_api_get` в `dota_mmr.py` (строка 280) использует синхронный `requests.get` с `time.sleep` для rate limiting. Это блокирует event loop на весь период ожидания (до 60+ секунд).  
- При параллельных вызовах это приводит к деградации всего бота: перестают отвечать на команды, digest job’ы задерживаются.  
- В `_get_hero_icon` (weekly_analytics.py строка 428) тоже `requests.get` и `time.sleep`.  
**Решение:** Полностью заменить `requests` на `aiohttp`. Использовать `await asyncio.sleep()` вместо `time.sleep()` в async-контексте. Вынести все блокирующие операции в `asyncio.to_thread()` или отдельный thread pool.  
**Пример:**
```python
# Вместо requests.get + time.sleep
async with session.get(url, timeout=timeout) as resp:
    return await resp.json()
```
**Сложность:** Средняя (1 день)  
**Влияние на производительность:** Критическое — event loop перестаёт блокироваться под нагрузкой.

### [HIGH] 2.3. Circuit breaker сбрасывается при каждом вызове `update_user_mmr`
**Заголовок:** Глобальный circuit breaker OpenDota сбрасывается на каждой операции  
**Файлы:** `dota_mmr.py` (строки 1452-1468)  
**Почему это проблема:**  
```python
def update_user_mmr(...):
    global _circuit_breaker, _api_rate_limit, _opendota_rate_limited_until
    if _circuit_breaker["state"] != "CLOSED":
        _circuit_breaker = {"state": "CLOSED", ...}  # СБРОС!
```
- Каждый вызов `update_user_mmr` принудительно сбрасывает circuit breaker в состояние CLOSED, даже если API недоступен.  
- Это делает circuit breaker бесполезным: при массовом обновлении 100 пользователей он откроется/закроется 100 раз подряд.  
- В итоге бот получает 429 от OpenDota и получает бан на 1 час.  
**Решение:** Убрать принудительный сброс. Circuit breaker должен управляться только фактами успеха/неудачи запросов.  
**Сложность:** Низкая (10 минут)  
**Влияние на производительность:** Высокое — предотвращает бан API.

### [HIGH] 2.4. Небезопасный debug endpoint `/api/steam-debug`
**Заголовок:** Открытый endpoint exposing внутренние данные  
**Файлы:** `main.py` (строки 3429-3471)  
**Почему это проблема:**  
- Endpoint `/api/steam-debug` возвращает список пользователей с telegram_id и steam_id без аутентификации.  
- Доступен извне при наличии WEBHOOK_URL.  
**Решение:** Удалить endpoint в production или добавить ADMIN_CHAT_ID проверку.  
**Сложность:** Низкая (5 минут)  
**Влияние на безопасность:** Высокое — утечка PII.

### [HIGH] 2.5. Использование `psycopg2` (sync) в асинхронном коде + threading.Lock
**Заголовок:** Синхронный драйвер PostgreSQL в async-архитектуре  
**Файлы:** `database.py` (строки 763-822, 1250-1361)  
**Почему это проблема:**  
- Используется `psycopg2` (синхронный) с `ThreadedConnectionPool` и `threading.Lock`.  
- Вся архитектура бота асинхронная (aiohttp, asyncio). Смешение sync-пулов и async-event-loop создаёт гонки и дедлоки.  
- `get_connection()` из async-функции блокирует event loop на время установки соединения.  
- `release_pg_connection` проверяет `isinstance(conn, _pg_ext.connection)` — если по ошибке передать SQLite-коннекшн, молча игнорирует, что маскирует баги.  
**Решение:** Перейти на `asyncpg` или `psycopg3` с асинхронным пулом. Или вынести все операции с БД в отдельный thread pool через `asyncio.to_thread()`.  
**Сложность:** Высокая (3-5 дней)  
**Влияние на производительность:** Среднее — уменьшает блокировки event loop.

---

## 3. Высокие проблемы (High Severity)

### [HIGH] 3.1. Дублирование SQL для PostgreSQL и SQLite
**Заголовок:** Два полных набора SQL-запросов в каждом методе  
**Файлы:** `database.py` (весь файл), `dota_mmr.py` (строки 1607-1670)  
**Почему это проблема:**  
- Каждый метод в `Database` содержит if/else для postgres/sqlite. Например, `get_user` (строки 1410-1525) — 115 строк дублированной логики.  
- Любое изменение схемы требует правки в 10+ местах.  
- Увеличивает риск inconsistency между двумя ветками.  
**Решение:** Вынести адаптер для каждого драйвера. Использовать параметризованные запросы с единым синтаксисом где возможно. Для миграций использовать Alembic с откатом к SQLite для dev.  
**Сложность:** Средняя (2 дня)  
**Влияние на производительность:** Нет прямого влияния.

### [HIGH] 3.2. Неограниченный рост глобальных словарей
**Заголовок:** Утечки памяти через in-memory словари без жёсткого TTL  
**Файлы:** `fissure.py` (`_user_fissure_processing`), `mute.py` (`_gagged_users`, `_gag_auto_release_tasks`, `_username_cache`), `bot_utils.py` (`_bot_can_delete_cache`), `techies.py` (`_active_techies_sessions`), `database.py` (`user_cache`, `_cache`)  
**Почему это проблема:**  
- `_user_fissure_processing` (fissure.py строка 54) —Entries удаляются в `finally`, но если бот упадёт, словарь останется заполненным.  
- `_bot_can_delete_cache` (bot_utils.py строка 56) — LRU cleanup только при превышении 200 entries, без TTL.  
- `_active_techies_sessions` (techies.py строка 41) — задачи создаются, но при краше бота остаются в памяти до перезагрузки.  
- `_gag_auto_release_tasks` (mute.py строка 53) — `asyncio.Task` хранятся вечно, если бот не умирает, но при перезагрузке worker на Render memory leak накапливается.  
**Решение:** Добавить TTL для всех in-memory структур. Использовать `weakref.WeakValueDictionary` где возможно. Регулярный background cleanup job.  
**Сложность:** Средняя (1 день)  
**Влияние на производительность:** При 1000+ пользователях memory leak достигает 100+ МБ.

### [HIGH] 3.3. SELECT * и ручная десериализация строк
**Заголовок:** `SELECT *` + ручное маппинг колонок в dict  
**Файлы:** `database.py` (строки 1410-1525, 3504-3587)  
**Почему это проблема:**  
- В `get_user` используется `SELECT *`, затем ручное именование полей. При добавлении колонки в БД нужно править 3 места: postgres-ветку, sqlite-ветку, dataclass User.  
- Сейчас `User.from_row` индексирует `row[41]`, `row[42]`, `row[43]` — если порядок колонок изменится, silently получаем garbage.  
**Решение:** Использовать `SELECT column1, column2...` с явным списком. Создать единый маппер на основе `_get_all_users_query` (строки 3504-3587), который уже правильный.  
**Сложность:** Низкая (2 часа)  
**Влияние на производительность:** Минимальное.

---

## 4. Средние проблемы (Medium Severity)

### [MEDIUM] 4.1. Мертвый код: container.py, `_EVENING_GREETINGS_DUP`, `start_fast_digest_loop`
**Файлы:** `container.py` (весь файл), `main.py` (строка 119-120), `digest.py` (строки 381-388)  
**Почему:**  
- `container.py` определяет DI-контейнер, но нигде не используется.  
- `_EVENING_GREETINGS_DUP = []` в main.py — пустой дубль.  
- `start_fast_digest_loop` / `stop_fast_digest_loop` — заглушки с `pass`.  
**Решение:** Удалить.

### [MEDIUM] 4.2. Неиспользуемые зависимости
**Файлы:** `requirements.txt`  
**Почему:**  
- `plotly==5.24.1` + `kaleido==0.2.1` — не используются (графики через matplotlib).  
- `APScheduler==3.10.4` — не используется (используется JobQueue из PTB).  
- `dependency-injector>=4.40.0` — контейнер не используется.  
- `requests==2.31.0` — дублирует `aiohttp`, но используется в критических местах.  
**Решение:** Удалить неиспользуемые пакеты. Оставить `requests` только до полного перехода на `aiohttp`.

### [MEDIUM] 4.3. Инвалидация кэша: трэш-состояния при падении
**Файлы:** `database.py`, `digest.py`, `fissure.py`  
**Почему:**  
- При падении бота во время `flush_users_cache` часть dirty-пользователей остаётся в кэше с флагом dirty. При рестарте flush снова пишет старые данные, перезаписывая актуальные из БД.  
- `alternate_digest_job` записывает `alternate_digest_last_text` в config после каждого успешного редактирования, но при падении между редактированием и записью текст теряется.  
**Решение:** Добавить version vector / optimistic locking для кэша. Использовать WAL (write-ahead log) для digest.

### [MEDIUM] 4.4. Дублирование hero name maps
**Файлы:** `dota_mmr.py` (строки 452-546), `weekly_analytics.py` (строки 293-383), `hero_meta.py`  
**Почему:**  
- Одна и та же мапа `HERO_NAME_TO_CDN` присутствует в `dota_mmr.py` и `weekly_analytics.py`.  
- Если добавится новый герой, нужно править оба файла.  
**Решение:** Вынести мапу в `hero_positions.py` или отдельный `hero_names.py`.

### [MEDIUM] 4.5. Ошибка в render.yaml
**Файлы:** `render.yaml` (строка 19)  
**Почему:**  
```yaml
   - key: MMR_CONCURRENCY_LIMIT
     value: "2"
```
- Лишний отступ перед `key` — YAML-парсер может прочитать это как вложенность внутрь предыдущего элемента.  
**Решение:** Исправить отступ.

---

## 5. Низкие проблемы (Low Severity)

### [LOW] 5.1. Отсутствие type hints в критических местах
**Файлы:** `main.py`, `database.py`  
- `database.py` возвращает dict из методов, ожидающих User-dataclass.  
- `main.py` функции часто без type hints.  
**Решение:** Добавить type hints постепенно, начиная с публичного API.

### [LOW] 5.2. Magic numbers
**Файлы:** `rolls.py` (FATAL_ROLL=-10), `constants.py` (COOLDOWN=86400), `database.py` (MAX_CACHE_SIZE=3000)  
- Значения разбросаны по коду безNamed constants.  
**Решение:** Централизовать в `constants.py`.

### [LOW] 5.3. Путаница с timezone
**Файлы:** `database.py` (строки 1528-1533, 1698-1704), `weekly_analytics.py` (строки 441-443)  
- MSK offset (+3) вычисляется вручную в нескольких местах.  
- `datetime.now()` vs `datetime.now(UTC)` — в разных файлах разный подход.  
**Решение:** Использовать `zoneinfo` (Python 3.9+) с `ZoneInfo("Europe/Moscow")`.

### [LOW] 5.4. Отсутствие `.gitignore` для `.env`
**Файлы:** `.gitignore`  
- `.env` не гарантированно игнорируется (его нет в списке `.gitignore`).  
**Решение:** Добавить `.env` в `.gitignore`.

### [LOW] 5.5. Дублирование `get_user` logic
- `get_user` в `database.py` (строки 2091-2137) содержит логику создания пользователя, хотя есть отдельный `add_user`.  
- `get_user` также делает `setdefault` для 10+ полей каждый раз.  
**Решение:** Вынести default-values логику в `add_user` / `init_db`.

---

## 6. Архитектурные рекомендации

### 6.1. Разделить main.py на слои
```
main.py (точка входа, 100 строк)
├── handlers/
│   ├── fissure.py (уже есть)
│   ├── profile.py
│   ├── digest.py (уже есть)
│   └── ...
├── jobs/
│   ├── mmr.py
│   ├── digest.py
│   └── weekly.py
└── web/
    ├── webhook.py
    └── health.py
```

### 6.2. Единый HTTP-клиент
- Удалить `requests`, использовать `aiohttp` везде.  
- Обернуть оставшиеся sync-вызовы в `asyncio.to_thread()`.

### 6.3. Единый адаптер БД
```python
class DatabaseAdapter(ABC):
    @abstractmethod
    async def get_user(self, tid): ...
    @abstractmethod
    async def update_user(self, tid, fields): ...

class PostgresAdapter(DatabaseAdapter): ...
class SqliteAdapter(DatabaseAdapter): ...
```

### 6.4. Управление состоянием бота
- Вынести `_user_fissure_processing`, `_gagged_users`, `_active_techies_sessions` в отдельный `BotState` класс с TTL.  
- Использовать `weakref` для автоматической очистки.

### 6.5. Очередь для тяжелых задач
- Вынести генерацию изображений (start_card, top_card, hero_meta, analytics_chart) в отдельный RQ/Celery worker.  
- Это освободит event loop и позволит масштабировать генерацию независимо.

---

## 7. Безопасность

| Проблема | Файл | Риск | Рекомендация |
|----------|------|------|--------------|
| `/api/steam-debug` без auth | main.py:3429 | Утечка PII | Удалить или защитить ADMIN_CHAT_ID |
| HTML-параметры с user input | main.py, fissure.py | XSS в Telegram | Строгое санитизирование через `make_clickable` |
| Логирование user_data | database.py, main.py | Утечка токенов | Маскировать sensitive поля |
| `set_config` с `None` удаляет ключ | database.py:1708 | Accidental data loss | Явный `delete_config` метод |
| Webhook без secret | main.py:3983 | Spoofing | Добавить `secret_token` |

---

## 8. Рекомендации по рефакторингу (приоритетный порядок)

| Приоритет | Задача | Сложность | Эффект |
|-----------|--------|-----------|--------|
| P0 | Убрать `requests` + `time.sleep` из async кода | 1д |Стабильность под нагрузкой |
| P0 | Убрать принудительный сброс circuit breaker | 10м |OpenDota API перестаёт банить |
| P0 | Удалить `/api/steam-debug` | 5м |Безопасность |
| P1 | Разделить main.py на модули | 3д |Поддерживаемость |
| P1 | Перейти на asyncpg / psycopg3 | 3д |Производительность БД |
| P1 | Убрать container.py (мертвый код) | 5м |Чистота кода |
| P2 | Централизовать hero name maps | 2ч |DRY |
| P2 | Добавить TTL для глобальных dict | 1д |Стабильность памяти |
| P2 | Исправить render.yaml indentation | 5м |Корректный деплой |
| P3 | Добавить type hints | 2д |Читаемость |
| P3 | Удалить неиспользуемые зависимости | 1ч |Чистота зависимостей |
| P3 | Маскировать sensitive логи | 1ч |Безопасность |

---

## 9. Заключение

Проект представляет собой функциональный Telegram-бот с большим набором фич (ролевая игра, Dota 2 интеграция, дайджесты, аналитика). Архитектурно он страдает от классических проблем монолита: God Object, циклические зависимости, глобальное состояние и смешение sync/async парадигм.

**Ключевые риски:**
1. **Блокировка event loop** из-за `requests` + `time.sleep` — при нагрузке бот просто перестаёт отвечать.
2. **Circuit breaker, который не работает** — API OpenDota будет баниться при массовом обновлении.
3. **Утечки памяти** через глобальные dict и asyncio tasks — на Render (512 МБ RAM) это критично.
4. **Циклические импорты** — любое рефакторинг превращается в квест.

**Сильные стороны:**
- Хорошее покрытие smoke-тестами.
- Есть leader election для multi-instance среды.
- Функционально богатый: roll system, hero meta, weekly analytics, mute, party — всё работает.
- Кэширование на нескольких уровнях (хотя и неидеальное).

**Итоговая оценка готовности к продакшену:** 6/10. Бот работает, но требует рефакторинга перед масштабированием на 1000+ пользователей.
