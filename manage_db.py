#!/usr/bin/env python3
import os
import sys
import subprocess

def run_alembic_command(args):
    """Запуск команды alembic с корректными путями"""
    # Убедимся, что мы в правильной директории
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Путь к alembic.ini (может потребоваться для Windows)
    alembic_ini_path = os.path.join(script_dir, 'alembic.ini')
    
    print(f"📁 Рабочая директория: {script_dir}")
    print(f"🔧 Конфиг: {alembic_ini_path}")
    
    # Проверяем существование alembic.ini
    if not os.path.exists(alembic_ini_path):
        print(f"❌ Файл {alembic_ini_path} не найден!")
        print("Создайте его командой: alembic init alembic")
        sys.exit(1)
    
    # Формируем полную команду
    cmd = ['alembic', '-c', alembic_ini_path] + args
    
    print(f"▶️  Выполняю команду: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ Ошибка выполнения команды:")
        if e.stderr:
            print(e.stderr)
        if e.stdout:
            print(e.stdout)
        return False
    except FileNotFoundError:
        print("❌ Команда 'alembic' не найдена. Установите alembic:")
        print("pip install alembic")
        return False

def create_migration(message):
    """Создание новой миграции"""
    print(f"🚀 Создание миграции: {message}")
    success = run_alembic_command(['revision', '--autogenerate', '-m', message])
    if success:
        print("✅ Миграция создана успешно!")
    else:
        print("❌ Не удалось создать миграцию")
        sys.exit(1)

def upgrade_database():
    """Применение миграций"""
    print("⬆️  Применение миграций...")
    success = run_alembic_command(['upgrade', 'head'])
    if success:
        print("✅ Миграции применены успешно!")
    else:
        print("❌ Не удалось применить миграции")
        sys.exit(1)

def downgrade_database(revision='-1'):
    """Откат миграций"""
    print(f"⬇️  Откат миграции до: {revision}")
    success = run_alembic_command(['downgrade', revision])
    if success:
        print("✅ Откат выполнен успешно!")
    else:
        print("❌ Не удалось выполнить откат")
        sys.exit(1)

def show_current():
    """Показать текущую ревизию"""
    print("📊 Текущая ревизия базы данных:")
    run_alembic_command(['current'])

def show_history():
    """Показать историю миграций"""
    print("📜 История миграций:")
    run_alembic_command(['history'])

def init_alembic():
    """Инициализация alembic"""
    print("🛠️  Инициализация Alembic...")
    try:
        result = subprocess.run(
            ['alembic', 'init', 'alembic'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("✅ Alembic инициализирован")
            print("ℹ️  Не забудьте настроить alembic.ini и env.py")
        else:
            print("❌ Ошибка инициализации:")
            print(result.stderr)
    except FileNotFoundError:
        print("❌ Команда 'alembic' не найдена. Установите alembic:")
        print("pip install alembic")

def print_help():
    """Показать справку"""
    print("""
Управление миграциями базы данных

Использование:
  python manage_db.py [команда] [аргументы]

Команды:
  init                 - Инициализировать alembic
  create "описание"    - Создать новую миграцию
  upgrade              - Применить все миграции
  downgrade [ревизия]  - Откатить миграцию (по умолчанию: -1)
  current              - Показать текущую ревизию
  history              - Показать историю миграций
  help                 - Показать эту справку

Примеры:
  python manage_db.py init
  python manage_db.py create "Добавил таблицу пользователей"
  python manage_db.py upgrade
  python manage_db.py downgrade
  python manage_db.py downgrade base
  python manage_db.py current
  python manage_db.py history
""")

def main():
    if len(sys.argv) < 2:
        print_help()
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'create' or command == 'create_migration':
        if len(sys.argv) < 3:
            print("❌ Укажите описание миграции")
            print("Пример: python manage_db.py create 'Добавил новую таблицу'")
            sys.exit(1)
        message = sys.argv[2]
        create_migration(message)
    
    elif command == 'upgrade':
        upgrade_database()
    
    elif command == 'downgrade':
        revision = sys.argv[2] if len(sys.argv) > 2 else '-1'
        downgrade_database(revision)
    
    elif command == 'current':
        show_current()
    
    elif command == 'history':
        show_history()
    
    elif command == 'init':
        init_alembic()
    
    elif command == 'help':
        print_help()
    
    else:
        print(f"❌ Неизвестная команда: {command}")
        print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()