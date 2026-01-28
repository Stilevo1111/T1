#!/usr/bin/env python3
"""
Точка входа для запуска fissure-bot на сервере
"""

import os
import sys

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Импортируем и запускаем основной модуль
if __name__ == "__main__":
    from main import main
    main()
