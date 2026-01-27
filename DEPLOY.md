# Деплой Fissure Bot на Render

## Подготовка проекта

Проект уже подготовлен для деплоя на Render. Все необходимые файлы созданы:

- `requirements.txt` - зависимости Python
- `render.yaml` - конфигурация Render
- `bot.py` - основной файл бота
- `.env.example` - пример файла окружения

## Шаги для деплоя

### 1. Создание Telegram бота

1. Напишите @BotFather в Telegram
2. Используйте команду `/newbot`
3. Следуйте инструкциям для создания бота
4. Получите токен бота

### 2. Настройка Render

1. Перейдите на [Render.com](https://render.com)
2. Создайте новое Web Service
3. Выберите репозиторий GitHub
4. Укажите URL вашего репозитория

### 3. Настройка переменных окружения

В настройках сервиса Render добавьте переменные окружения:

```
BOT_TOKEN=your_telegram_bot_token_here
DATABASE_URL=sqlite:///fissure_bot.db
RENDER_EXTERNAL_URL=https://your-app-name.onrender.com
PORT=10000
```

### 4. Настройка команды запуска

Render автоматически использует команду из `render.yaml`:
```bash
python bot.py
```

### 5. Запуск деплоя

1. Нажмите "Deploy" в Render
2. Дождитесь завершения деплоя
3. Проверьте логи на наличие ошибок

## Альтернативные способы запуска

### Локальный запуск

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Создайте файл `.env`:
```bash
cp .env.example .env
```

3. Заполните `.env` своими значениями

4. Запустите бота:
```bash
python bot.py
```

### Docker

1. Соберите образ:
```bash
docker build -t fissure-bot .
```

2. Запустите контейнер:
```bash
docker run -p 10000:10000 fissure-bot
```

### Docker Compose

1. Создайте `.env` файл с переменными окружения
2. Запустите:
```bash
docker-compose up -d
```

## Проверка работоспособности

1. Запустите тест:
```bash
python test_bot.py
```

2. Проверьте импорты:
```bash
python -c "import sys; sys.path.append('.'); from config import validate_config; print('OK')"
```

## Устранение неполадок

### Ошибка: "No such file or directory: 'requirements.txt'"

Убедитесь, что файл `requirements.txt` существует в корне проекта.

### Ошибка: "BOT_TOKEN not found"

Проверьте, что переменная `BOT_TOKEN` установлена в окружении.

### Ошибка: "Database connection failed"

Проверьте настройки `DATABASE_URL` в окружении.

### Ошибка: "Port already in use"

Измените порт в переменной `PORT` или в `render.yaml`.

## Поддержка

Если возникнут проблемы:
1. Проверьте логи в Render
2. Запустите `python test_bot.py` для диагностики
3. Убедитесь, что все зависимости установлены

## Файлы проекта

```
fissure-bot/
├── bot.py              # Основной файл бота
├── config.py           # Конфигурация
├── database.py         # Работа с базой данных
├── game_logic.py       # Игровая логика
├── requirements.txt    # Зависимости
├── render.yaml         # Конфигурация Render
├── .env.example        # Пример окружения
├── README.md           # Документация
├── test_bot.py         # Тесты
├── run.py             # Быстрый запуск
├── Dockerfile         # Docker образ
├── docker-compose.yml # Docker Compose
├── .gitignore         # Игнорируемые файлы
└── handlers/          # Обработчики команд
    ├── __init__.py
    ├── fissure.py
    └── pvp_system.py