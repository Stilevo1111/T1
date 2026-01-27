# Fissure Bot

Telegram бот для игры в трещины и PvP бои.

## Особенности

- 🎮 Прохождение трещин для увеличения длины
- ⚔️ PvP бои с другими игроками
- 📊 Система уровней и прокачки персонажа
- 🏆 Рейтинги по MMR, уровню и длине фиссуры
- 🎯 Система талантов и характеристик

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/hidlor/fissure-bot.git
cd fissure-bot
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Настройте окружение:
```bash
cp .env.example .env
# Отредактируйте .env файл с вашими настройками
```

4. Запустите бота:
```bash
python bot.py
```

## Настройка окружения

Создайте файл `.env` с следующими переменными:

```env
BOT_TOKEN=your_telegram_bot_token_here
DATABASE_URL=sqlite:///fissure_bot.db
RENDER_EXTERNAL_URL=https://your-app-name.onrender.com
PORT=10000
```

## Команды бота

- `/start` - Зарегистрироваться в боте
- `/help` - Показать список команд
- `/stats` - Показать статистику персонажа
- `/fissure` - Пройти трещину (раз в 24 часа)
- `/pvp` - Поиск PvP противника
- `/fight` - Быстрый бой с рандомным противником
- `/top_mmr` - Топ игроков по MMR
- `/top_level` - Топ игроков по уровню
- `/top_fissure` - Топ игроков по длине фиссуры
- `/info` - Информация о боте

## Развертывание на Render

1. Создайте новое Web Service на Render
2. Укажите репозиторий GitHub
3. Установите переменные окружения в настройках сервиса
4. Укажите команду запуска: `python bot.py`

## Требования

- Python 3.10+
- PostgreSQL или SQLite
- Telegram Bot Token

## Лицензия

MIT License