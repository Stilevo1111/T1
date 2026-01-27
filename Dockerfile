FROM python:3.13-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Установка рабочей директории
WORKDIR /app

# Копирование файлов
COPY requirements.txt .
COPY .env.example .env
COPY . .

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Создание пользователя для безопасности
RUN useradd --create-home --shell /bin/bash app

# Смена владельца файлов
RUN chown -R app:app /app

# Смена пользователя
USER app

# Команда запуска
CMD ["python", "bot.py"]