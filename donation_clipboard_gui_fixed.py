#!/usr/bin/env python3
"""
Donation Clipboard Manager - GUI Version (Fixed)

Графический интерфейс для управления никнеймами по ранжировке донатов.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv
import pyperclip
import threading
import time
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
        self.monitor_thread = None
        
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
                return True
            except Exception as e:
                return False
        return False
    
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
            return True
        except Exception as e:
            return False
    
    def add_user(self, username: str, amount: float):
        """Добавление пользователя с суммой доната"""
        username = username.strip()
        self.donations[username] = amount
        return self.save_data()
    
    def get_ranked_list(self) -> List[Tuple[str, float]]:
        """Получение отсортированного списка по убыванию донатов"""
        return sorted(self.donations.items(), key=lambda x: x[1], reverse=True)
    
    def copy_next_user(self):
        """Копирование следующего пользователя в буфер"""
        ranked = self.get_ranked_list()
        if not ranked:
            return None, 0, 0
        
        # Увеличиваем индекс перед получением пользователя
        self.current_index += 1
        if self.current_index >= len(ranked):
            self.current_index = 0
        
        username, amount = ranked[self.current_index]
        pyperclip.copy(username)
        print(f"DEBUG: Копируем пользователя {username} (позиция {self.current_index + 1})")
        
        return username, amount, self.current_index + 1
    
    def start_monitoring(self, callback):
        """Запуск мониторинга буфера обмена"""
        if not self.donations:
            return False
        
        self.is_running = True
        self.last_clipboard_content = pyperclip.paste()
        
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
                        callback()
                    
                    time.sleep(0.1)  # Проверка каждые 100мс
                    
                except Exception as e:
                    print(f"Ошибка мониторинга: {e}")
                    time.sleep(1)
        
        # Запускаем мониторинг в отдельном потоке
        self.monitor_thread = threading.Thread(target=monitor, daemon=True)
        self.monitor_thread.start()
        return True
    
    def stop_monitoring(self):
        """Остановка мониторинга"""
        self.is_running = False


class DonationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Donation Clipboard Manager")
        self.root.geometry("800x600")
        self.root.configure(bg='#2b2b2b')
        
        # Инициализация менеджера
        self.manager = DonationManager()
        
        # Переменные состояния
        self.monitoring = False
        self.current_user = tk.StringVar(value="Текущий пользователь: -")
        self.position_info = tk.StringVar(value="Позиция: -")
        
        self.setup_ui()
        self.update_ranking()
        
    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        # Стили
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#2b2b2b')
        style.configure('TLabel', background='#2b2b2b', foreground='white')
        style.configure('TButton', background='#404040', foreground='white')
        style.map('TButton', background=[('active', '#505050')])
        
        # Главный фрейм
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Верхняя панель управления
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill='x', pady=(0, 10))
        
        # Панель добавления пользователя
        add_frame = ttk.LabelFrame(top_frame, text="Добавить пользователя", padding=10)
        add_frame.pack(side='left', fill='y', padx=(0, 10))
        
        ttk.Label(add_frame, text="Никнейм:").grid(row=0, column=0, sticky='w', pady=2)
        self.username_entry = ttk.Entry(add_frame, width=20)
        self.username_entry.grid(row=0, column=1, padx=(5, 0), pady=2)
        
        ttk.Label(add_frame, text="Сумма доната:").grid(row=1, column=0, sticky='w', pady=2)
        self.amount_entry = ttk.Entry(add_frame, width=10)
        self.amount_entry.grid(row=1, column=1, padx=(5, 0), pady=2)
        
        add_btn = ttk.Button(add_frame, text="Добавить", command=self.add_user)
        add_btn.grid(row=0, column=2, rowspan=2, padx=(10, 0), pady=2)
        
        # Панель управления мониторингом
        control_frame = ttk.LabelFrame(top_frame, text="Управление", padding=10)
        control_frame.pack(side='left', fill='y', padx=(0, 10))
        
        self.start_btn = ttk.Button(control_frame, text="Запустить мониторинг", command=self.toggle_monitoring)
        self.start_btn.pack(side='left', padx=(0, 5))
        
        copy_btn = ttk.Button(control_frame, text="Скопировать следующего", command=self.copy_next)
        copy_btn.pack(side='left', padx=(0, 5))
        
        # Панель редактирования
        edit_frame = ttk.LabelFrame(top_frame, text="Редактирование", padding=10)
        edit_frame.pack(side='left', fill='y', padx=(0, 10))
        
        edit_btn = ttk.Button(edit_frame, text="Редактировать", command=self.edit_user)
        edit_btn.pack(side='left', padx=(0, 5))
        
        delete_btn = ttk.Button(edit_frame, text="Удалить", command=self.delete_user)
        delete_btn.pack(side='left', padx=(0, 5))
        
        # Информационная панель
        info_frame = ttk.LabelFrame(top_frame, text="Информация", padding=10)
        info_frame.pack(side='left', fill='both', expand=True)
        
        ttk.Label(info_frame, textvariable=self.current_user).pack(anchor='w')
        ttk.Label(info_frame, textvariable=self.position_info).pack(anchor='w')
        
        # Таблица рейтинга
        ranking_frame = ttk.LabelFrame(main_frame, text="Рейтинг по донатам", padding=10)
        ranking_frame.pack(fill='both', expand=True)
        
        # Создаем Treeview для таблицы
        columns = ('position', 'username', 'amount')
        self.tree = ttk.Treeview(ranking_frame, columns=columns, show='headings', height=15)
        
        # Настройка заголовков
        self.tree.heading('position', text='Позиция')
        self.tree.heading('username', text='Никнейм')
        self.tree.heading('amount', text='Донат')
        
        # Настройка ширины колонок
        self.tree.column('position', width=80, anchor='center')
        self.tree.column('username', width=200)
        self.tree.column('amount', width=100, anchor='e')
        
        # Скроллбар
        scrollbar = ttk.Scrollbar(ranking_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Нижняя панель
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill='x', pady=(10, 0))
        
        save_btn = ttk.Button(bottom_frame, text="Сохранить данные", command=self.save_data)
        save_btn.pack(side='left', padx=(0, 5))
        
        load_btn = ttk.Button(bottom_frame, text="Загрузить данные", command=self.load_data)
        load_btn.pack(side='left', padx=(0, 5))
        
        import_btn = ttk.Button(bottom_frame, text="Импортировать из CSV", command=self.import_from_csv)
        import_btn.pack(side='left', padx=(0, 5))
        
        clear_btn = ttk.Button(bottom_frame, text="Очистить список", command=self.clear_data)
        clear_btn.pack(side='left', padx=(0, 5))
        
        # Статус бар
        self.status_var = tk.StringVar(value="Готов")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief='sunken', anchor='w')
        status_bar.pack(fill='x', pady=(5, 0))
        
    def add_user(self):
        """Добавление пользователя"""
        username = self.username_entry.get().strip()
        amount_str = self.amount_entry.get().strip()
        
        if not username or not amount_str:
            messagebox.showwarning("Ошибка", "Заполните все поля")
            return
        
        try:
            amount = float(amount_str)
        except ValueError:
            messagebox.showwarning("Ошибка", "Сумма доната должна быть числом")
            return
        
        if self.manager.add_user(username, amount):
            self.username_entry.delete(0, tk.END)
            self.amount_entry.delete(0, tk.END)
            self.update_ranking()
            self.status_var.set(f"Добавлен пользователь: {username} - {amount}")
        else:
            messagebox.showerror("Ошибка", "Не удалось сохранить данные")
    
    def update_ranking(self):
        """Обновление таблицы рейтинга"""
        # Очищаем таблицу
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        ranked = self.manager.get_ranked_list()
        
        for i, (username, amount) in enumerate(ranked, 1):
            marker = "→" if i == self.manager.current_index + 1 else ""
            self.tree.insert('', 'end', values=(f"{marker} {i}", username, f"{amount}"))
        
        # Обновляем информацию о текущем пользователе
        if ranked:
            current_user, amount, position = self.manager.copy_next_user()
            if current_user:
                self.current_user.set(f"Текущий пользователь: {current_user}")
                self.position_info.set(f"Позиция: {position} из {len(ranked)}")
            else:
                self.current_user.set("Текущий пользователь: -")
                self.position_info.set("Позиция: -")
        else:
            self.current_user.set("Текущий пользователь: -")
            self.position_info.set("Позиция: -")
    
    def copy_next(self):
        """Копирование следующего пользователя"""
        # При ручном нажатии кнопки просто копируем следующего, не увеличивая индекс
        ranked = self.manager.get_ranked_list()
        if not ranked:
            messagebox.showinfo("Информация", "Нет пользователей для копирования")
            print("DEBUG: Нет пользователей для копирования")
            return
        
        # Получаем текущего пользователя без изменения индекса
        username, amount = ranked[self.manager.current_index]
        pyperclip.copy(username)
        self.update_ranking()
        self.status_var.set(f"Скопировано: {username} (позиция {self.manager.current_index + 1})")
        print(f"DEBUG: Скопировано {username}, позиция {self.manager.current_index + 1}")
    
    def toggle_monitoring(self):
        """Включение/выключение мониторинга"""
        if not self.monitoring:
            if not self.manager.donations:
                messagebox.showwarning("Ошибка", "Сначала добавьте пользователей")
                return
            
            self.monitoring = True
            self.start_btn.config(text="Остановить мониторинг")
            self.start_btn.config(style='Accent.TButton')
            
            # Запускаем мониторинг
            self.manager.start_monitoring(self.on_clipboard_change)
            self.status_var.set("Мониторинг буфера обмена запущен")
        else:
            self.monitoring = False
            self.start_btn.config(text="Запустить мониторинг")
            self.start_btn.config(style='TButton')
            
            # Останавливаем мониторинг
            self.manager.stop_monitoring()
            self.status_var.set("Мониторинг остановлен")
    
    def on_clipboard_change(self):
        """Обработчик изменения буфера обмена"""
        # Увеличиваем индекс для перехода к следующему пользователю
        ranked = self.manager.get_ranked_list()
        if ranked:
            self.manager.current_index += 1
            if self.manager.current_index >= len(ranked):
                self.manager.current_index = 0
            
            # Копируем следующего пользователя
            username, amount = ranked[self.manager.current_index]
            pyperclip.copy(username)
            self.update_ranking()
            self.status_var.set(f"Скопировано: {username} (позиция {self.manager.current_index + 1})")
            print(f"DEBUG: Автоматически переключились на {username}, позиция {self.manager.current_index + 1}")
    
    def save_data(self):
        """Сохранение данных"""
        if self.manager.save_data():
            self.status_var.set("Данные сохранены")
        else:
            messagebox.showerror("Ошибка", "Не удалось сохранить данные")
    
    def load_data(self):
        """Загрузка данных"""
        if self.manager.load_data():
            self.update_ranking()
            self.status_var.set("Данные загружены")
        else:
            messagebox.showwarning("Предупреждение", "Не удалось загрузить данные")
    
    def edit_user(self):
        """Редактирование пользователя"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Ошибка", "Выберите пользователя для редактирования")
            return
        
        # Получаем данные выбранного пользователя
        item = self.tree.item(selected[0])
        values = item['values']
        username = values[1]
        current_amount = float(values[2])
        
        # Создаем диалог редактирования
        edit_window = tk.Toplevel(self.root)
        edit_window.title("Редактировать пользователя")
        edit_window.geometry("300x150")
        edit_window.transient(self.root)
        edit_window.grab_set()
        
        ttk.Label(edit_window, text="Никнейм:").grid(row=0, column=0, sticky='w', padx=10, pady=10)
        username_entry = ttk.Entry(edit_window, width=20)
        username_entry.insert(0, username)
        username_entry.grid(row=0, column=1, padx=10, pady=10)
        
        ttk.Label(edit_window, text="Сумма доната:").grid(row=1, column=0, sticky='w', padx=10, pady=10)
        amount_entry = ttk.Entry(edit_window, width=10)
        amount_entry.insert(0, str(current_amount))
        amount_entry.grid(row=1, column=1, padx=10, pady=10)
        
        def save_edit():
            new_username = username_entry.get().strip()
            new_amount_str = amount_entry.get().strip()
            
            if not new_username or not new_amount_str:
                messagebox.showwarning("Ошибка", "Заполните все поля")
                return
            
            try:
                new_amount = float(new_amount_str)
            except ValueError:
                messagebox.showwarning("Ошибка", "Сумма доната должна быть числом")
                return
            
            # Удаляем старого пользователя и добавляем нового
            if username in self.manager.donations:
                del self.manager.donations[username]
            
            self.manager.add_user(new_username, new_amount)
            self.update_ranking()
            self.status_var.set(f"Обновлен пользователь: {new_username} - {new_amount}")
            edit_window.destroy()
        
        save_btn = ttk.Button(edit_window, text="Сохранить", command=save_edit)
        save_btn.grid(row=2, column=0, columnspan=2, pady=10)
    
    def delete_user(self):
        """Удаление пользователя"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Ошибка", "Выберите пользователя для удаления")
            return
        
        # Получаем данные выбранного пользователя
        item = self.tree.item(selected[0])
        values = item['values']
        username = values[1]
        
        if messagebox.askyesno("Подтверждение", f"Вы действительно хотите удалить пользователя {username}?"):
            if username in self.manager.donations:
                del self.manager.donations[username]
                self.manager.save_data()
                self.update_ranking()
                self.status_var.set(f"Удален пользователь: {username}")
    
    def import_from_csv(self):
        """Импорт данных из CSV файла"""
        file_path = filedialog.askopenfilename(
            title="Выберите CSV файл",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if not file_path:
            return
        
        try:
            imported_count = 0
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    username = row['username'].strip()
                    amount = float(row['amount'])
                    self.manager.donations[username] = amount
                    imported_count += 1
            
            self.manager.save_data()
            self.update_ranking()
            self.status_var.set(f"Импортировано {imported_count} пользователей из {file_path}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось импортировать данные: {e}")
    
    def clear_data(self):
        """Очистка данных"""
        if messagebox.askyesno("Подтверждение", "Вы действительно хотите очистить все данные?"):
            self.manager.donations.clear()
            self.manager.current_index = 0
            self.update_ranking()
            self.status_var.set("Данные очищены")


def main():
    root = tk.Tk()
    app = DonationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()