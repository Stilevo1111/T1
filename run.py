#!/usr/bin/env python3
"""
Быстрый запуск Fissure Bot
"""

import sys
import os

# Добавляем путь к проекту
sys.path.append('.')

if __name__ == '__main__':
    try:
        # Импортируем и запускаем основной бот
        from bot import main
        import asyncio
        
        print("🚀 Запуск Fissure Bot...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен вручную")
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
        sys.exit(1)