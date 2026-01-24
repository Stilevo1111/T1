# Проблема с сохранением данных на Render

## Проблема
Данные игроков сбрасываются после каждого деплоя на Render, потому что файловая система эфемерная (временная).

## Решения

### Решение 1: PostgreSQL (Рекомендуется, БЕСПЛАТНО)

Render предоставляет бесплатную PostgreSQL базу данных.

#### Шаг 1: Создайте PostgreSQL базу
1. Откройте https://dashboard.render.com
2. Нажмите **"New +"** → **"PostgreSQL"**
3. Заполните:
   - Name: `fissure-bot-db`
   - Database: `fissure_bot`
   - User: `fissure_bot`
   - Region: выберите ближайший
   - Plan: **Free** (бесплатно)
4. Нажмите **"Create Database"**
5. Подождите 1-2 минуты пока создастся

#### Шаг 2: Получите DATABASE_URL
1. После создания откройте базу данных
2. Найдите **"Internal Database URL"**
3. Скопируйте URL (начинается с `postgresql://`)

#### Шаг 3: Добавьте DATABASE_URL в бота
1. Откройте ваш Web Service (fissure-bot)
2. Перейдите в **Environment**
3. Нажмите **"Add Environment Variable"**
4. Key: `DATABASE_URL`
5. Value: вставьте скопированный URL
6. Нажмите **"Save Changes"**

#### Шаг 4: Обновите код
Я обновлю код бота чтобы использовать PostgreSQL.

### Решение 2: Render Disk (Платно)

Render Disk - постоянное хранилище файлов.

#### Стоимость:
- $0.25/GB в месяц
- Минимум 1GB = $0.25/месяц

#### Настройка:
1. Откройте ваш Web Service
2. Перейдите в **Settings**
3. Найдите **"Disks"**
4. Нажмите **"Add Disk"**
5. Name: `data`
6. Mount Path: `/data`
7. Size: 1 GB
8. Нажмите **"Save"**

Затем нужно изменить путь к `data.json`:
```python
DATA_FILE = "/data/data.json"
```

### Решение 3: Внешнее хранилище (Бесплатно)

Использовать бесплатные сервисы:
- **JSONBin.io** - бесплатное JSON хранилище
- **MongoDB Atlas** - бесплатная NoSQL база
- **Supabase** - бесплатная PostgreSQL

## Рекомендация

**Используйте PostgreSQL от Render** - это:
- ✅ Бесплатно
- ✅ Быстро
- ✅ Надежно
- ✅ Интегрировано с Render
- ✅ Автоматические бэкапы

Я сейчас обновлю код чтобы поддерживать PostgreSQL.
