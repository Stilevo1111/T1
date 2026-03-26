#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok Studio Macro Recorder
Программа для записи и воспроизведения действий в TikTok Studio
"""

import time
import json
import logging
import threading
from typing import List, Dict, Any
from pynput import mouse, keyboard
from pynput.mouse import Button
from pynput.keyboard import Key
import pyautogui

class MacroRecorder:
    """Класс для записи и воспроизведения макросов"""
    
    def __init__(self, config_file: str = "macro_config.json"):
        """
        Инициализация рекордера
        
        Args:
            config_file: путь к файлу конфигурации
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.is_recording = False
        self.is_playing = False
        self.macro_data = []
        self.start_time = 0
        
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('macro_recorder.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Контроллеры
        self.mouse_listener = None
        self.keyboard_listener = None
        
    def _load_config(self) -> Dict:
        """Загрузка конфигурации"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {
                "delay_range": [1, 3],
                "max_retries": 3,
                "timeout": 10
            }
    
    def _save_config(self):
        """Сохранение конфигурации"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def start_recording(self):
        """Начать запись макроса"""
        if self.is_recording:
            self.logger.warning("Запись уже идет")
            return
        
        self.logger.info("Начинаем запись макроса...")
        self.is_recording = True
        self.macro_data = []
        self.start_time = time.time()
        
        # Запускаем слушатели
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
        
        print("Запись начата. Выполните действия в TikTok Studio.")
        print("Для остановки записи нажмите Ctrl+C")
        
        try:
            while self.is_recording:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.stop_recording()
    
    def stop_recording(self):
        """Остановить запись макроса"""
        if not self.is_recording:
            return
        
        self.is_recording = False
        
        # Останавливаем слушатели
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        
        self.logger.info(f"Запись завершена. Записано {len(self.macro_data)} действий")
        print(f"Запись завершена. Записано {len(self.macro_data)} действий")
        
        # Сохраняем макрос
        self.save_macro("recorded_macro.json")
    
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
    
    def save_macro(self, filename: str):
        """Сохранение макроса в файл"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.macro_data, f, indent=2, ensure_ascii=False)
        self.logger.info(f"Макрос сохранен в {filename}")
    
    def load_macro(self, filename: str) -> List[Dict]:
        """Загрузка макроса из файла"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                self.macro_data = json.load(f)
            self.logger.info(f"Макрос загружен из {filename}")
            return self.macro_data
        except FileNotFoundError:
            self.logger.error(f"Файл {filename} не найден")
            return []
    
    def play_macro(self, usernames: List[str]):
        """Воспроизведение макроса с подстановкой никнеймов"""
        if not self.macro_data:
            self.logger.error("Нет загруженного макроса для воспроизведения")
            return
        
        self.logger.info(f"Начинаем воспроизведение макроса для {len(usernames)} пользователей")
        
        # Разбиваем пользователей на группы по 40 человек
        batch_size = 40
        for i in range(0, len(usernames), batch_size):
            batch = usernames[i:i + batch_size]
            self.logger.info(f"Обрабатываем группу пользователей {i//batch_size + 1}: {len(batch)} человек")
            
            # Воспроизводим макрос для группы
            self._play_macro_for_batch(batch)
            
            # Задержка между группами
            time.sleep(2)
    
    def _play_macro_for_batch(self, usernames: List[str]):
        """Воспроизведение макроса для одной группы пользователей"""
        if not self.macro_data:
            return
        
        last_timestamp = 0
        
        for action in self.macro_data:
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
    
    def create_invitation_macro(self, usernames: List[str]):
        """
        Создание макроса для приглашения пользователей
        Этот метод создает макрос программно
        """
        self.macro_data = []
        current_time = 0
        
        # Имитация клика по кнопке "Поделиться эфиром"
        self.macro_data.append({
            "type": "mouse_click",
            "x": 100,  # Примерные координаты
            "y": 200,
            "button": "Button.left",
            "pressed": True,
            "timestamp": current_time
        })
        current_time += 0.1
        self.macro_data.append({
            "type": "mouse_click",
            "x": 100,
            "y": 200,
            "button": "Button.left",
            "pressed": False,
            "timestamp": current_time
        })
        current_time += 1.0
        
        # Имитация клика по полю ввода
        self.macro_data.append({
            "type": "mouse_click",
            "x": 300,  # Примерные координаты поля ввода
            "y": 400,
            "button": "Button.left",
            "pressed": True,
            "timestamp": current_time
        })
        current_time += 0.1
        self.macro_data.append({
            "type": "mouse_click",
            "x": 300,
            "y": 400,
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
        
        # Имитация клика по кнопке приглашения
        self.macro_data.append({
            "type": "mouse_click",
            "x": 500,  # Примерные координаты кнопки приглашения
            "y": 600,
            "button": "Button.left",
            "pressed": True,
            "timestamp": current_time
        })
        current_time += 0.1
        self.macro_data.append({
            "type": "mouse_click",
            "x": 500,
            "y": 600,
            "button": "Button.left",
            "pressed": False,
            "timestamp": current_time
        })
        
        self.logger.info(f"Создан программный макрос из {len(self.macro_data)} действий")
    
    def interactive_mode(self):
        """Интерактивный режим для записи и воспроизведения"""
        print("TikTok Studio Macro Recorder")
        print("=" * 40)
        print("1. Записать макрос")
        print("2. Воспроизвести макрос")
        print("3. Создать программный макрос")
        print("4. Выход")
        
        choice = input("Выберите действие: ")
        
        if choice == "1":
            self.start_recording()
        
        elif choice == "2":
            filename = input("Введите имя файла с макросом: ")
            usernames = input("Введите никнеймы через запятую: ").split(",")
            usernames = [username.strip() for username in usernames if username.strip()]
            
            if usernames:
                self.load_macro(filename)
                self.play_macro(usernames)
            else:
                print("Список пользователей пуст")
        
        elif choice == "3":
            usernames = input("Введите никнеймы через запятую: ").split(",")
            usernames = [username.strip() for username in usernames if username.strip()]
            
            if usernames:
                self.create_invitation_macro(usernames)
                self.save_macro("programmatic_macro.json")
                print("Программный макрос создан и сохранен")
            else:
                print("Список пользователей пуст")
        
        elif choice == "4":
            return
        else:
            print("Неверный выбор")


def main():
    """Основная функция"""
    recorder = MacroRecorder()
    recorder.interactive_mode()


if __name__ == "__main__":
    main()