#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok Studio GUI
Графический интерфейс для программы приглашения пользователей в TikTok Studio
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
import time
import json
import logging
from typing import List, Dict, Any
from pynput import mouse, keyboard
from pynput.mouse import Button
from pynput.keyboard import Key
import pyautogui

class TikTokStudioGUI:
    """Графический интерфейс для TikTok Studio Macro Recorder"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("TikTok Studio Auto Inviter")
        self.root.geometry("800x600")
        self.root.configure(bg='#2c3e50')
        
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('gui_inviter.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Переменные состояния
        self.is_recording = False
        self.is_playing = False
        self.macro_data = []
        self.mouse_listener = None
        self.keyboard_listener = None
        
        self.setup_ui()
    
    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        # Стили
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', font=('Arial', 10), padding=5)
        style.configure('TLabel', font=('Arial', 10), background='#2c3e50', foreground='white')
        style.configure('TEntry', font=('Arial', 10))
        
        # Главный фрейм
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Название программы
        title_label = ttk.Label(main_frame, text="TikTok Studio Auto Inviter", 
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # Фрейм для управления записью
        record_frame = ttk.LabelFrame(main_frame, text="Запись макроса", padding="10")
        record_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.record_button = ttk.Button(record_frame, text="Начать запись", 
                                       command=self.toggle_recording, style='TButton')
        self.record_button.grid(row=0, column=0, padx=(0, 10))
        
        self.stop_record_button = ttk.Button(record_frame, text="Остановить запись", 
                                           command=self.stop_recording, style='TButton', state='disabled')
        self.stop_record_button.grid(row=0, column=1, padx=(0, 10))
        
        self.save_macro_button = ttk.Button(record_frame, text="Сохранить макрос", 
                                          command=self.save_macro, style='TButton', state='disabled')
        self.save_macro_button.grid(row=0, column=2, padx=(0, 10))
        
        self.load_macro_button = ttk.Button(record_frame, text="Загрузить макрос", 
                                          command=self.load_macro, style='TButton')
        self.load_macro_button.grid(row=0, column=3)
        
        # Фрейм для пользователей
        users_frame = ttk.LabelFrame(main_frame, text="Пользователи для приглашения", padding="10")
        users_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(users_frame, text="Никнеймы (через запятую):").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        self.users_text = scrolledtext.ScrolledText(users_frame, height=4, width=70, font=('Arial', 10))
        self.users_text.grid(row=1, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.load_users_button = ttk.Button(users_frame, text="Загрузить из файла", 
                                          command=self.load_users_from_file, style='TButton')
        self.load_users_button.grid(row=2, column=0, padx=(0, 10))
        
        self.save_users_button = ttk.Button(users_frame, text="Сохранить список", 
                                          command=self.save_users_to_file, style='TButton')
        self.save_users_button.grid(row=2, column=1, padx=(0, 10))
        
        # Фрейм для воспроизведения
        play_frame = ttk.LabelFrame(main_frame, text="Воспроизведение макроса", padding="10")
        play_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.play_button = ttk.Button(play_frame, text="Воспроизвести макрос", 
                                    command=self.toggle_playing, style='TButton', state='disabled')
        self.play_button.grid(row=0, column=0, padx=(0, 10))
        
        self.stop_play_button = ttk.Button(play_frame, text="Остановить воспроизведение", 
                                         command=self.stop_playing, style='TButton', state='disabled')
        self.stop_play_button.grid(row=0, column=1, padx=(0, 10))
        
        # Фрейм для программного макроса
        program_frame = ttk.LabelFrame(main_frame, text="Программный макрос", padding="10")
        program_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(program_frame, text="Координаты кнопки 'Поделиться эфиром':").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        ttk.Label(program_frame, text="X:").grid(row=1, column=0, sticky=tk.W)
        self.share_x_entry = ttk.Entry(program_frame, width=10)
        self.share_x_entry.grid(row=1, column=1, padx=(0, 10))
        ttk.Label(program_frame, text="Y:").grid(row=1, column=2, sticky=tk.W)
        self.share_y_entry = ttk.Entry(program_frame, width=10)
        self.share_y_entry.grid(row=1, column=3, padx=(0, 20))
        
        ttk.Label(program_frame, text="Координаты поля ввода:").grid(row=2, column=0, sticky=tk.W, pady=(10, 5))
        ttk.Label(program_frame, text="X:").grid(row=3, column=0, sticky=tk.W)
        self.input_x_entry = ttk.Entry(program_frame, width=10)
        self.input_x_entry.grid(row=3, column=1, padx=(0, 10))
        ttk.Label(program_frame, text="Y:").grid(row=3, column=2, sticky=tk.W)
        self.input_y_entry = ttk.Entry(program_frame, width=10)
        self.input_y_entry.grid(row=3, column=3, padx=(0, 20))
        
        ttk.Label(program_frame, text="Координаты кнопки приглашения:").grid(row=4, column=0, sticky=tk.W, pady=(10, 5))
        ttk.Label(program_frame, text="X:").grid(row=5, column=0, sticky=tk.W)
        self.invite_x_entry = ttk.Entry(program_frame, width=10)
        self.invite_x_entry.grid(row=5, column=1, padx=(0, 10))
        ttk.Label(program_frame, text="Y:").grid(row=5, column=2, sticky=tk.W)
        self.invite_y_entry = ttk.Entry(program_frame, width=10)
        self.invite_y_entry.grid(row=5, column=3, padx=(0, 20))
        
        self.create_program_macro_button = ttk.Button(program_frame, text="Создать программный макрос", 
                                                    command=self.create_program_macro, style='TButton')
        self.create_program_macro_button.grid(row=6, column=0, pady=(10, 0))
        
        # Фрейм для статуса и логов
        status_frame = ttk.LabelFrame(main_frame, text="Статус и логи", padding="10")
        status_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.S), pady=(10, 0))
        
        self.status_label = ttk.Label(status_frame, text="Готов к работе", 
                                    font=('Arial', 10, 'bold'), foreground='green')
        self.status_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        self.log_text = scrolledtext.ScrolledText(status_frame, height=8, width=70, font=('Arial', 9))
        self.log_text.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        # Настройка растягивания
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        
        # Заполнение примерами координат
        self.share_x_entry.insert(0, "100")
        self.share_y_entry.insert(0, "200")
        self.input_x_entry.insert(0, "300")
        self.input_y_entry.insert(0, "400")
        self.invite_x_entry.insert(0, "500")
        self.invite_y_entry.insert(0, "600")
    
    def toggle_recording(self):
        """Переключение записи макроса"""
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()
    
    def start_recording(self):
        """Начать запись макроса"""
        if self.is_playing:
            messagebox.showwarning("Предупреждение", "Сначала остановите воспроизведение")
            return
        
        self.is_recording = True
        self.macro_data = []
        self.start_time = time.time()
        
        self.record_button.config(text="Остановить запись", style='TButton')
        self.stop_record_button.config(state='normal')
        self.save_macro_button.config(state='disabled')
        self.play_button.config(state='disabled')
        
        self.update_status("Идет запись макроса...", 'orange')
        self.log_message("Начата запись макроса")
        
        # Запускаем слушатели в отдельном потоке
        self.recording_thread = threading.Thread(target=self._start_listeners, daemon=True)
        self.recording_thread.start()
    
    def _start_listeners(self):
        """Запуск слушателей мыши и клавиатуры"""
        self.mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        
        self.mouse_listener.start()
        self.keyboard_listener.start()
        
        # Ждем, пока запись не будет остановлена
        while self.is_recording:
            time.sleep(0.1)
        
        self.mouse_listener.stop()
        self.keyboard_listener.stop()
    
    def stop_recording(self):
        """Остановить запись макроса"""
        if not self.is_recording:
            return
        
        self.is_recording = False
        self.record_button.config(text="Начать запись", style='TButton')
        self.stop_record_button.config(state='disabled')
        self.save_macro_button.config(state='normal')
        self.play_button.config(state='normal')
        
        self.update_status(f"Запись завершена. Записано {len(self.macro_data)} действий", 'green')
        self.log_message(f"Запись завершена. Записано {len(self.macro_data)} действий")
    
    def _on_mouse_move(self, x, y):
        """Обработка движения мыши"""
        if self.is_recording:
            self.macro_data.append({
                "type": "mouse_move",
                "x": x,
                "y": y,
                "timestamp": time.time() - self.start_time
            })
    
    def _on_mouse_click(self, x, y, button, pressed):
        """Обработка кликов мыши"""
        if self.is_recording:
            self.macro_data.append({
                "type": "mouse_click",
                "x": x,
                "y": y,
                "button": str(button),
                "pressed": pressed,
                "timestamp": time.time() - self.start_time
            })
    
    def _on_mouse_scroll(self, x, y, dx, dy):
        """Обработка скроллинга мыши"""
        if self.is_recording:
            self.macro_data.append({
                "type": "mouse_scroll",
                "x": x,
                "y": y,
                "dx": dx,
                "dy": dy,
                "timestamp": time.time() - self.start_time
            })
    
    def _on_key_press(self, key):
        """Обработка нажатия клавиш"""
        if self.is_recording:
            self.macro_data.append({
                "type": "key_press",
                "key": str(key),
                "timestamp": time.time() - self.start_time
            })
    
    def _on_key_release(self, key):
        """Обработка отпускания клавиш"""
        if self.is_recording:
            self.macro_data.append({
                "type": "key_release",
                "key": str(key),
                "timestamp": time.time() - self.start_time
            })
    
    def save_macro(self):
        """Сохранение макроса в файл"""
        if not self.macro_data:
            messagebox.showwarning("Предупреждение", "Нет данных для сохранения")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(self.macro_data, f, indent=2, ensure_ascii=False)
                self.log_message(f"Макрос сохранен в {filename}")
                messagebox.showinfo("Успех", f"Макрос сохранен в {filename}")
            except Exception as e:
                self.log_message(f"Ошибка при сохранении: {e}")
                messagebox.showerror("Ошибка", f"Не удалось сохранить макрос: {e}")
    
    def load_macro(self):
        """Загрузка макроса из файла"""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    self.macro_data = json.load(f)
                self.log_message(f"Макрос загружен из {filename}")
                self.play_button.config(state='normal')
                messagebox.showinfo("Успех", f"Макрос загружен из {filename}")
            except Exception as e:
                self.log_message(f"Ошибка при загрузке: {e}")
                messagebox.showerror("Ошибка", f"Не удалось загрузить макрос: {e}")
    
    def toggle_playing(self):
        """Переключение воспроизведения макроса"""
        if not self.is_playing:
            self.start_playing()
        else:
            self.stop_playing()
    
    def start_playing(self):
        """Начать воспроизведение макроса"""
        if not self.macro_data:
            messagebox.showwarning("Предупреждение", "Сначала загрузите или запишите макрос")
            return
        
        users_text = self.users_text.get("1.0", tk.END).strip()
        if not users_text:
            messagebox.showwarning("Предупреждение", "Введите никнеймы пользователей")
            return
        
        usernames = [username.strip() for username in users_text.split(',') if username.strip()]
        if not usernames:
            messagebox.showwarning("Предупреждение", "Введите корректные никнеймы")
            return
        
        self.is_playing = True
        self.play_button.config(text="Остановить", style='TButton')
        self.stop_play_button.config(state='normal')
        self.record_button.config(state='disabled')
        
        self.update_status("Идет воспроизведение макроса...", 'blue')
        self.log_message(f"Начато воспроизведение макроса для {len(usernames)} пользователей")
        
        # Запускаем воспроизведение в отдельном потоке
        self.playing_thread = threading.Thread(
            target=self._play_macro_thread, args=(usernames,), daemon=True
        )
        self.playing_thread.start()
    
    def _play_macro_thread(self, usernames):
        """Поток для воспроизведения макроса"""
        try:
            self.play_macro(usernames)
        except Exception as e:
            self.log_message(f"Ошибка при воспроизведении: {e}")
            messagebox.showerror("Ошибка", f"Ошибка при воспроизведении: {e}")
        finally:
            self.root.after(0, self._finish_playing)
    
    def _finish_playing(self):
        """Завершение воспроизведения"""
        self.is_playing = False
        self.play_button.config(text="Воспроизвести макрос", style='TButton')
        self.stop_play_button.config(state='disabled')
        self.record_button.config(state='normal')
        self.update_status("Воспроизведение завершено", 'green')
        self.log_message("Воспроизведение завершено")
    
    def stop_playing(self):
        """Остановить воспроизведение макроса"""
        if self.is_playing:
            self.is_playing = False
            self._finish_playing()
    
    def play_macro(self, usernames):
        """Воспроизведение макроса с подстановкой никнеймов"""
        # Разбиваем пользователей на группы по 40 человек
        batch_size = 40
        for i in range(0, len(usernames), batch_size):
            if not self.is_playing:
                break
                
            batch = usernames[i:i + batch_size]
            self.log_message(f"Обработка группы {i//batch_size + 1}: {len(batch)} пользователей")
            
            # Воспроизводим макрос для группы
            self._play_macro_for_batch(batch)
            
            # Задержка между группами
            if self.is_playing:
                time.sleep(2)
    
    def _play_macro_for_batch(self, usernames):
        """Воспроизведение макроса для одной группы пользователей"""
        if not self.macro_data:
            return
        
        last_timestamp = 0
        
        for action in self.macro_data:
            if not self.is_playing:
                break
                
            # Вычисляем задержку
            delay = action["timestamp"] - last_timestamp
            if delay > 0:
                time.sleep(delay)
            last_timestamp = action["timestamp"]
            
            # Выполняем действие
            if action["type"] == "mouse_move":
                pyautogui.moveTo(action["x"], action["y"])
            
            elif action["type"] == "mouse_click":
                button = Button.left if "left" in action["button"] else Button.right
                if action["pressed"]:
                    pyautogui.mouseDown(action["x"], action["y"], button=button.name)
                else:
                    pyautogui.mouseUp(action["x"], action["y"], button=button.name)
            
            elif action["type"] == "mouse_scroll":
                pyautogui.scroll(action["dy"], action["x"], action["y"])
            
            elif action["type"] == "key_press":
                try:
                    # Обработка специальных клавиш
                    if hasattr(Key, action["key"].replace("Key.", "")):
                        key = getattr(Key, action["key"].replace("Key.", ""))
                    else:
                        key = action["key"].replace("'", "")
                    
                    pyautogui.keyDown(key)
                except:
                    pass
            
            elif action["type"] == "key_release":
                try:
                    # Обработка специальных клавиш
                    if hasattr(Key, action["key"].replace("Key.", "")):
                        key = getattr(Key, action["key"].replace("Key.", ""))
                    else:
                        key = action["key"].replace("'", "")
                    
                    pyautogui.keyUp(key)
                except:
                    pass
            
            elif action["type"] == "type_text":
                # Это наше кастомное действие для ввода текста
                text = action["text"]
                pyautogui.typewrite(text)
    
    def create_program_macro(self):
        """Создание программного макроса"""
        try:
            # Получаем координаты из полей ввода
            share_x = int(self.share_x_entry.get())
            share_y = int(self.share_y_entry.get())
            input_x = int(self.input_x_entry.get())
            input_y = int(self.input_y_entry.get())
            invite_x = int(self.invite_x_entry.get())
            invite_y = int(self.invite_y_entry.get())
            
            users_text = self.users_text.get("1.0", tk.END).strip()
            if not users_text:
                messagebox.showwarning("Предупреждение", "Введите никнеймы пользователей")
                return
            
            usernames = [username.strip() for username in users_text.split(',') if username.strip()]
            if not usernames:
                messagebox.showwarning("Предупреждение", "Введите корректные никнеймы")
                return
            
            # Создаем программный макрос
            self.macro_data = []
            current_time = 0
            
            # Клик по кнопке "Поделиться эфиром"
            self.macro_data.append({
                "type": "mouse_click",
                "x": share_x,
                "y": share_y,
                "button": "Button.left",
                "pressed": True,
                "timestamp": current_time
            })
            current_time += 0.1
            self.macro_data.append({
                "type": "mouse_click",
                "x": share_x,
                "y": share_y,
                "button": "Button.left",
                "pressed": False,
                "timestamp": current_time
            })
            current_time += 1.0
            
            # Клик по полю ввода
            self.macro_data.append({
                "type": "mouse_click",
                "x": input_x,
                "y": input_y,
                "button": "Button.left",
                "pressed": True,
                "timestamp": current_time
            })
            current_time += 0.1
            self.macro_data.append({
                "type": "mouse_click",
                "x": input_x,
                "y": input_y,
                "button": "Button.left",
                "pressed": False,
                "timestamp": current_time
            })
            current_time += 0.5
            
            # Ввод пользователей
            users_string = ",".join(usernames)
            self.macro_data.append({
                "type": "type_text",
                "text": users_string,
                "timestamp": current_time
            })
            current_time += 1.0
            
            # Клик по кнопке приглашения
            self.macro_data.append({
                "type": "mouse_click",
                "x": invite_x,
                "y": invite_y,
                "button": "Button.left",
                "pressed": True,
                "timestamp": current_time
            })
            current_time += 0.1
            self.macro_data.append({
                "type": "mouse_click",
                "x": invite_x,
                "y": invite_y,
                "button": "Button.left",
                "pressed": False,
                "timestamp": current_time
            })
            
            self.log_message(f"Создан программный макрос из {len(self.macro_data)} действий")
            self.play_button.config(state='normal')
            messagebox.showinfo("Успех", f"Программный макрос создан из {len(self.macro_data)} действий")
            
        except ValueError:
            messagebox.showwarning("Предупреждение", "Введите корректные координаты")
        except Exception as e:
            self.log_message(f"Ошибка при создании макроса: {e}")
            messagebox.showerror("Ошибка", f"Ошибка при создании макроса: {e}")
    
    def load_users_from_file(self):
        """Загрузка списка пользователей из файла"""
        filename = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    users = f.read().strip()
                self.users_text.delete("1.0", tk.END)
                self.users_text.insert("1.0", users)
                self.log_message(f"Список пользователей загружен из {filename}")
                messagebox.showinfo("Успех", f"Список пользователей загружен из {filename}")
            except Exception as e:
                self.log_message(f"Ошибка при загрузке: {e}")
                messagebox.showerror("Ошибка", f"Не удалось загрузить список: {e}")
    
    def save_users_to_file(self):
        """Сохранение списка пользователей в файл"""
        users_text = self.users_text.get("1.0", tk.END).strip()
        if not users_text:
            messagebox.showwarning("Предупреждение", "Нет данных для сохранения")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(users_text)
                self.log_message(f"Список пользователей сохранен в {filename}")
                messagebox.showinfo("Успех", f"Список пользователей сохранен в {filename}")
            except Exception as e:
                self.log_message(f"Ошибка при сохранении: {e}")
                messagebox.showerror("Ошибка", f"Не удалось сохранить список: {e}")
    
    def update_status(self, text, color):
        """Обновление статуса"""
        self.status_label.config(text=text, foreground=color)
    
    def log_message(self, message):
        """Добавление сообщения в лог"""
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
        self.logger.info(message)


def main():
    """Основная функция"""
    root = tk.Tk()
    app = TikTokStudioGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()