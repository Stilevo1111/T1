"""
Скрипт для исправления ошибки 409 Conflict
Сбрасывает webhook и очищает pending updates
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ Ошибка: BOT_TOKEN не найден в .env файле")
    print("Создайте файл .env и добавьте: BOT_TOKEN=ваш_токен")
    exit(1)

print("🔧 Исправление конфликта 409...")
print(f"Токен: {BOT_TOKEN[:10]}...")

# 1. Удаляем webhook (если был установлен)
print("\n1️⃣ Удаление webhook...")
url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true"
response = requests.get(url)
result = response.json()
print(f"   Результат: {result}")

# 2. Получаем информацию о боте
print("\n2️⃣ Проверка бота...")
url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
response = requests.get(url)
result = response.json()
if result.get("ok"):
    bot_info = result.get("result", {})
    print(f"   ✅ Бот: @{bot_info.get('username')}")
    print(f"   ID: {bot_info.get('id')}")
else:
    print(f"   ❌ Ошибка: {result}")
    exit(1)

# 3. Очищаем pending updates
print("\n3️⃣ Очистка pending updates...")
url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset=-1"
response = requests.get(url)
result = response.json()
print(f"   Результат: {result.get('ok')}")

print("\n✅ Готово! Теперь можно запускать бота.")
print("   Подождите 10-20 секунд перед запуском.")
