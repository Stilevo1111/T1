#!/usr/bin/env python3
"""
Donation Clipboard Manager

Программа для управления никнеймами по ранжировке донатов.
Копирует никнеймы по одному в буфер обмена, автоматически переключается на следующий
после того, как вы вставите текущий никнейм.

Функционал:
- Загрузка и сохранение данных о донатах в CSV файле
- Ранжировка по сумме донатов (от большего к меньшему)
- Автоматическое копирование следующего ника в буфер после вставки
- Простой интерфейс для просмотра текущего списка и позиции
"""

import csv
import pyperclip
import time
import threading
import sys
from datetime import datetime
from typing import List, Dict, Tuple
import os


class DonationManager:
    def __init__(self, data_file: str = "donations.csv"):
        self.data_file = data_file
        self.donations: Dict[str, float] = {}
        self.current_index = 0
        self.is_running = False
        self.last_clipboard_content = ""
        
        # Загружаем данные при инициализации
        self.load_data()
        
    def load_data(self):
        """Загрузка данных из CSV файла"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        username = row['username'].strip()
                        amount = float(row['amount'])
                        self.donations[username] = amount
                print(f"✓ Загружено {len(self.donations)} пользователей из {self.data_file}")
            except Exception as e:
                print(f"⚠ Ошибка загрузки данных: {e}")
        else:
            print(f"ℹ Файл {self.data_file} не найден, будет создан при добавлении данных")
    
    def save_data(self):
        """Сохранение данных в CSV файл"""
        try:
            with open(self.data_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ['username', 'amount', 'date_added']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for username, amount in self.donations.items():
                    writer.writerow({
                        'username': username,
                        'amount': amount,
                        'date_added': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
            print(f"✓ Данные сохранены в {self.data_file}")
        except Exception as e:
            print(f"⚠ Ошибка сохранения данных: {e}")
    
    def add_user(self, username: str, amount: float):
        """Добавление пользователя с суммой доната"""
        username = username.strip()
        if username in self.donations:
            print(f"⚠ Пользователь {username} уже существует. Обновляем сумму...")
        
        self.donations[username] = amount
        self.save_data()
        print(f"✓ Добавлен/обновлен пользователь: {username} - {amount}")
    
    def get_ranked_list(self) -> List[Tuple[str, float]]:
        """Получение отсортированного списка по убыванию донатов"""
        return sorted(self.donations.items(), key=lambda x: x[1], reverse=True)
    
    def get_current_user(self) -> Tuple[str, float]:
        """Получение текущего пользователя"""
        ranked = self.get_ranked_list()
        if not ranked:
            return None, 0
        
        if self.current_index >= len(ranked):
            self.current_index = 0
        
        return ranked[self.current_index]
    
    def copy_next_user(self):
        """Копирование следующего пользователя в буфер"""
        ranked = self.get_ranked_list()
        if not ranked:
            print("❌ Нет пользователей для копирования")
            return False
        
        if self.current_index >= len(ranked):
            self.current_index = 0
        
        username, amount = ranked[self.current_index]
        pyperclip.copy(username)
        
        print(f"\n📋 Скопировано в буфер: {username} (донат: {amount})")
        print(f"📍 Позиция: {self.current_index + 1} из {len(ranked)}")
        print("💡 Вставьте никнейм, и следующий автоматически скопируется в буфер")
        
        return True
    
    def start_monitoring(self):
        """Запуск мониторинга буфера обмена"""
        if not self.donations:
            print("❌ Нет пользователей для мониторинга")
            return
        
        self.is_running = True
        self.last_clipboard_content = pyperclip.paste()
        
        print("\n🔍 Мониторинг буфера обмена запущен...")
        print("Для остановки нажмите Ctrl+C")
        
        # Сразу копируем первого пользователя
        self.copy_next_user()
        
        def monitor():
            while self.is_running:
                try:
                    current_content = pyperclip.paste()
                    
                    # Если содержимое буфера изменилось (пользователь вставил ник)
                    if current_content != self.last_clipboard_content:
                        self.last_clipboard_content = current_content
                        
                        # Переходим к следующему пользователю
                        self.current_index += 1
                        time.sleep(0.5)  # Небольшая задержка перед копированием следующего
                        self.copy_next_user()
                    
                    time.sleep(0.1)  # Проверка каждые 100мс
                    
                except Exception as e:
                    print(f"⚠ Ошибка мониторинга: {e}")
                    time.sleep(1)
        
        # Запускаем мониторинг в отдельном потоке
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
    
    def stop_monitoring(self):
        """Остановка мониторинга"""
        self.is_running = False
        print("\n🛑 Мониторинг остановлен")
    
    def show_ranking(self):
        """Показать текущий рейтинг"""
        ranked = self.get_ranked_list()
        if not ranked:
            print("❌ Нет данных для отображения рейтинга")
            return
        
        print("\n🏆 ТОП по донатам:")
        print("-" * 50)
        for i, (username, amount) in enumerate(ranked, 1):
            marker = " → " if i == self.current_index + 1 else "   "
            print(f"{marker}{i:2d}. {username:20s} - {amount}")
        print("-" * 50)


def main():
    manager = DonationManager()
    
    print("🎯 Donation Clipboard Manager")
    print("=" * 50)
    
    while True:
        try:
            print("\nВыберите действие:")
            print("1. Добавить/обновить пользователя")
            print("2. Показать рейтинг")
            print("3. Запустить мониторинг буфера")
            print("4. Скопировать следующего пользователя")
            print("5. Выход")
            
            choice = input("\nВаш выбор (1-5): ").strip()
            
            if choice == '1':
                username = input("Введите никнейм: ").strip()
                try:
                    amount = float(input("Введите сумму доната: "))
                    manager.add_user(username, amount)
                except ValueError:
                    print("❌ Некорректная сумма доната")
            
            elif choice == '2':
                manager.show_ranking()
            
            elif choice == '3':
                if manager.donations:
                    manager.start_monitoring()
                    # Ждем, пока пользователь не нажмет Ctrl+C
                    try:
                        while manager.is_running:
                            time.sleep(0.1)
                    except KeyboardInterrupt:
                        manager.stop_monitoring()
                else:
                    print("❌ Сначала добавьте пользователей")
            
            elif choice == '4':
                manager.copy_next_user()
            
            elif choice == '5':
                print("👋 До свидания!")
                break
            
            else:
                print("❌ Некорректный выбор")
                
        except KeyboardInterrupt:
            print("\n👋 До свидания!")
            break
        except Exception as e:
            print(f"⚠ Ошибка: {e}")


if __name__ == "__main__":
    # Проверяем наличие pyperclip
    try:
        import pyperclip
    except ImportError:
        print("❌ Требуется установка pyperclip: pip install pyperclip")
        sys.exit(1)
    
    main()