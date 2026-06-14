# AUDIT REPORT - fissure-bot on Render + Neon

## ⚠️ P0 — КРИТИЧЕСКИЕ (Падает прямо сейчас)

### 1. Блокирующий `requests.get` вместо `aiohttp`
**Файл:** `dota_mmr.py:24, 212, 360, 387, 469, 660, 1496, 1560, 1645, 1738, 1835`

**Причина:** 11 синхронных HTTP запросов блокируют event loop. При каждом обращении к API OpenDota or Dota2 или любым внешним сервисам бот зависает.

**Исправление:**
```python
# Вместо requests.get использовать aiohttp
async def _api_get_async(url, params=None, timeout=10):
    from database import get_aiohttp_session
    session = await get_aiohttp_session()
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        if resp.status == 200:
            return await resp.json()
        return None
```

### 2. `time.sleep` вместо `asyncio.sleep`
**Файл:** `dota_mmr.py:205, 221, 229`

**Причина:** `time.sleep` блокирует весь event loop на 3-5 секунд. При rate limiting все остальные операции останавливаются.

**Исправление:**
```python
# Вместо time.sleep
await asyncio.sleep(e.wait_seconds)
```

### 3. Отсутствие connection pool для PostgreSQL
**Файл:** `database.py:577-616`

**Причина:** Каждый запрос создаёт новое соединение. На Render Free PostgreSQL соединения заканчиваются, Neon рекомендует использовать pooler.

**Исправление:**
```python
# Использовать pgbouncer connection string
# DATABASE_URL вида: postgres://...neon.tech/...?pgbouncer=true
# или добавить connection pool
```

---

## ⚠️ P1 — ВЫСОКИЙ ПРИОРИТЕТ (Упадёт под нагрузкой)

### 4. N+1 запросы при обновлении MMR
**Файл:** `main.py:1063-1076`

**Причина:** Для КАЖДОГО пользователя отдельный вызов `update_user_mmr` → отдельный запрос к OpenDota API. При 100 игроках = 100 запросов.

**Исправление:**
```python
# Использовать batch запросы к API или кэшировать результаты
# Добавить bulk fetch матчей для всех игроков
```

### 5. Отсутствие таймаутов на внешние API
**Файл:** `dota_mmr.py:212` (`_api_get`)

**Причина:** Нет общего timeout, запросы могут висять бесконечно.

**Исправление:**
```python
# Добавить timeout в requests.get
r = requests.get(url, params=params, timeout=10)
```

### 6. Глобальные переменные вместо Redis cache
**Файл:** `hero_meta.py:419-423`, `dota_mmr.py:16-17`

**Причина:** При деплое на Render Free инстанс рестартует, кеш в памяти пропадает.

**Исправление:**
```python
# Использовать bot_config таблицу как cache storage (уже реализовано частично)
# Или добавить Redis
```

---

## ⚠️ P2 — ОПТИМИЗАЦИЯ

### 7. SQLAlchemy-style ORM отсутствует
**Файл:** `database.py`

**Причина:** Прямые SQL запросы везде, нельзя легко оптимизировать.

### 8. Отсутствие индексов на часто используемые колонки
**Файл:** `database.py` (создание таблиц)

**Причина:** `steam_id`, `week_games`, `mmr` - часто используются в WHERE/ORDER BY.

---

## ⚠️ P3 — УЛУЧШЕНИЯ

### 9. Отсутствует healthcheck endpoint
**Файл:** `render.yaml`

**Причина:** Render не может проверить готовность сервиса.

### 10. Нет graceful shutdown
**Файл:** `main.py`

**Причина:** При SIGTERM соединения не закрываются корректно.

---

## 📊 3 ГЛАВНЫЕ МЕТРИКИ ДЛЯ МОНИТОРИНГА

1. **Event Loop Blocked Time** - время блокировки event loop (должно быть < 100ms)
2. **PostgreSQL Connection Count** - количество соединений (не > 20 на Render Free)
3. **OpenDota API Response Time** - время ответа API (не > 5s)

---

## ✅ DEPLOY CHECKLIST

- [ ] Заменить `requests.get` → `aiohttp` + `asyncio.sleep`
- [ ] Добавить timeout на все внешние API вызовы
- [ ] Проверить connection string содержит `sslmode=require`
- [ ] Добавить индексы: `CREATE INDEX idx_users_steam_id ON users(steam_id)`
- [ ] Добавить healthcheck endpoint `/health`
- [ ] Убедиться что все синхронные операции в `asyncio.to_thread`