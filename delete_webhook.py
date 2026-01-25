import os
import requests
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Получаем токен
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("BOT_TOKEN не найден в .env файле")
    print("Проверяю .env файл...")
    try:
        with open('.env', 'r') as f:
            content = f.read()
            print(f"Содержимое .env файла: {content}")
    except:
        print("Файл .env не найден")
    exit(1)

print(f"Использую токен: {BOT_TOKEN[:10]}...")

# URL для удаления вебхука
url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"

try:
    print(f"Отправляю запрос: {url}")
    response = requests.post(url)
    result = response.json()
    
    print(f"Получен ответ: {result}")
    
    if result.get("ok"):
        print("✅ Вебхук успешно удален!")
        print(f"Результат: {result}")
    else:
        print("❌ Ошибка при удалении вебхука:")
        print(f"Результат: {result}")
        
except Exception as e:
    print(f"❌ Ошибка: {e}")
