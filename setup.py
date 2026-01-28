#!/usr/bin/env python3
"""
Скрипт для быстрой настройки fissure-bot
"""

import os
import sys

def create_env_file():
    """Создает файл .env с примером токена"""
    env_content = """# Файл конфигурации fissure-bot
# Вставьте сюда токен вашего Telegram бота
BOT_TOKEN=ваш_токен_бота_здесь
"""
    
    if os.path.exists('.env'):
        print("⚠️  Файл .env уже существует")
        return False
    
    with open('.env', 'w', encoding='utf-8') as f:
        f.write(env_content)
    
    print("✅ Файл .env создан")
    return True

def install_requirements():
    """Устанавливает зависимости"""
    print("📦 Устанавливаем зависимости...")
    os.system('pip install -r requirements.txt')
    print("✅ Зависимости установлены")

def init_database():
    """Инициализирует базу данных"""
    try:
        import db
        db.init_db()
        print("✅ База данных инициализирована")
        return True
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных: {e}")
        return False

def main():
    """Основная функция настройки"""
    print("🚀 Настройка fissure-bot\n")
    
    # Создаем .env файл
    create_env_file()
    
    # Устанавливаем зависимости
    install_requirements()
    
    # Инициализируем базу данных
    if not init_database():
        return False
    
    print("\n🎉 Настройка завершена!")
    print("\nЧто дальше:")
    print("1. Откройте файл .env и вставьте ваш BOT_TOKEN")
    print("2. Запустите бота: python main.py")
    print("3. Начните играть в Telegram!")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)