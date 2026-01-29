#!/usr/bin/env python3
"""
Database management script for fissure-bot

Usage:
    python manage_db.py migrate          # Run migrations
    python manage_db.py create_migration  # Create new migration
    python manage_db.py status           # Check migration status
    python manage_db.py downgrade        # Rollback last migration
"""

import os
import sys
import subprocess
from pathlib import Path

def run_alembic_command(command, *args):
    """Run an Alembic command with proper environment setup"""
    # Set database URL for SQLite during development
    env = os.environ.copy()
    if 'DATABASE_URL' not in env:
        env['DATABASE_URL'] = 'test.db'
    
    cmd = [sys.executable, '-m', 'alembic'] + list(command) + list(args)
    
    try:
        result = subprocess.run(cmd, env=env, cwd=Path(__file__).parent, 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Команда выполнена успешно:")
            print(result.stdout)
            return True
        else:
            print("❌ Ошибка выполнения команды:")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"❌ Ошибка запуска команды: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python manage_db.py migrate          # Запустить миграции")
        print("  python manage_db.py create_migration  # Создать новую миграцию")
        print("  python manage_db.py status           # Проверить статус миграций")
        print("  python manage_db.py downgrade        # Откатить последнюю миграцию")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "migrate":
        print("🚀 Запуск миграций базы данных...")
        success = run_alembic_command('upgrade', 'head')
        if success:
            print("🎉 Миграции успешно применены!")
        else:
            print("💥 Ошибка при применении миграций!")
            sys.exit(1)
    
    elif command == "create_migration":
        if len(sys.argv) < 3:
            print("❌ Укажите описание миграции:")
            print("  python manage_db.py create_migration 'Описание изменений'")
            sys.exit(1)
        
        description = ' '.join(sys.argv[2:])
        print(f"🚀 Создание новой миграции: {description}")
        success = run_alembic_command('revision', '--autogenerate', '-m', description)
        if success:
            print("🎉 Миграция успешно создана!")
        else:
            print("💥 Ошибка при создании миграции!")
            sys.exit(1)
    
    elif command == "status":
        print("📊 Проверка статуса миграций...")
        run_alembic_command('current')
    
    elif command == "downgrade":
        print("🔙 Откат последней миграции...")
        success = run_alembic_command('downgrade', '-1')
        if success:
            print("🎉 Миграция успешно отменена!")
        else:
            print("💥 Ошибка при отмене миграции!")
            sys.exit(1)
    
    else:
        print(f"❌ Неизвестная команда: {command}")
        print("Доступные команды: migrate, create_migration, status, downgrade")
        sys.exit(1)

if __name__ == "__main__":
    main()