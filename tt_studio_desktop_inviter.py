#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok Studio Desktop Auto Inviter
Автоматическое приглашение пользователей в TikTok Studio (desktop приложение)
"""

import time
import json
import random
import logging
import subprocess
import pyautogui
from typing import List, Dict, Optional
from pynput.keyboard import Key, Controller as KeyboardController
from pynput.mouse import Button, Controller as MouseController

class TikTokStudioDesktopInviter:
    """Класс для автоматического приглашения пользователей в desktop версии TikTok Studio"""
    
    def __init__(self, config_file: str = "tt_desktop_config.json"):
        """
        Инициализация инвайтера для desktop приложения
        
        Args:
            config_file: путь к файлу конфигурации
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('tt_desktop_inviter.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def _load_config(self) -> Dict:
        """Загрузка конфигурации из JSON файла"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.warning(f"Конфигурационный файл {self.config_file} не найден, используем значения по умолчанию")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict:
        """Получение конфигурации по умолчанию"""
        return {
            "delay_range": [1, 3],
            "max_retries": 3,
            "timeout": 10,
            "tiktok_studio_path": "C:\\Program Files\\TikTok\\TikTok Studio.exe"
        }
    
    def _save_config(self):
        """Сохранение конфигурации в JSON файл"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def random_delay(self):
        """Случайная задержка между действиями"""
        delay = random.uniform(*self.config["delay_range"])
        time.sleep(delay)
    
    def launch_tiktok_studio(self) -> bool:
        """Запуск TikTok Studio desktop приложения"""
        try:
            self.logger.info("Запускаем TikTok Studio...")
            
            # Запускаем приложение
            subprocess.Popen(self.config["tiktok_studio_path"])
            self.random_delay()
            
            # Ждем загрузки приложения
            time.sleep(5)
            
            self.logger.info("TikTok Studio запущен")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка при запуске TikTok Studio: {e}")
            return False
    
    def find_and_click_element(self, image_path: str, confidence: float = 0.8) -> bool:
        """
        Поиск элемента на экране по изображению и клик по нему
        
        Args:
            image_path: путь к изображению элемента
            confidence: уровень уверенности в поиске (0.0 - 1.0)
            
        Returns:
            bool: True если элемент найден и кликнули, False в противном случае
        """
        try:
            # Ищем элемент на экране
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            
            if location:
                # Кликаем по центру найденного элемента
                center = pyautogui.center(location)
                pyautogui.click(center)
                self.random_delay()
                return True
            else:
                self.logger.warning(f"Элемент {image_path} не найден на экране")
                return False
                
        except Exception as e:
            self.logger.error(f"Ошибка при поиске элемента {image_path}: {e}")
            return False
    
    def type_text(self, text: str):
        """Ввод текста с клавиатуры"""
        self.keyboard.type(text)
        self.random_delay()
    
    def invite_users_to_stream(self, usernames: List[str]) -> Dict[str, bool]:
        """
        Приглашение пользователей в эфир TikTok Studio (до 40 человек за раз)
        
        Args:
            usernames: список никнеймов для приглашения
            
        Returns:
            Dict[str, bool]: словарь с результатами для каждого пользователя
        """
        results = {}
        
        try:
            self.logger.info("Начинаем процесс приглашения пользователей")
            
            # Ищем и кликаем по вкладке "Поделиться эфиром"
            # Для этого нужно создать изображения элементов интерфейса
            share_button_found = False
            
            # Пытаемся найти кнопку "Поделиться эфиром" по нескольким возможным изображениям
            share_images = [
                "images/share_stream_button.png",
                "images/share_button.png",
                "images/stream_share.png"
            ]
            
            for image_path in share_images:
                if self.find_and_click_element(image_path, confidence=0.7):
                    share_button_found = True
                    break
            
            if not share_button_found:
                self.logger.warning("Кнопка 'Поделиться эфиром' не найдена, пытаемся найти вручную")
                # Если не нашли по изображению, пробуем найти по координатам или другим способам
                # Это заглушка - в реальной реализации нужно будет создать изображения элементов
            
            # Ищем поле для ввода пользователей
            input_field_found = False
            input_images = [
                "images/user_input_field.png",
                "images/username_input.png",
                "images/input_field.png"
            ]
            
            for image_path in input_images:
                if self.find_and_click_element(image_path, confidence=0.7):
                    input_field_found = True
                    break
            
            if not input_field_found:
                self.logger.warning("Поле для ввода пользователей не найдено")
                return {username: False for username in usernames}
            
            # Разбиваем пользователей на группы по 40 человек
            batch_size = 40
            for i in range(0, len(usernames), batch_size):
                batch = usernames[i:i + batch_size]
                self.logger.info(f"Обрабатываем группу пользователей {i//batch_size + 1}: {len(batch)} человек")
                
                # Вводим пользователей через запятую
                users_string = ",".join(batch)
                self.type_text(users_string)
                self.random_delay()
                
                # Ищем и кликаем кнопку приглашения
                invite_button_found = False
                invite_images = [
                    "images/invite_button.png",
                    "images/send_invitations.png",
                    "images/invite_users.png"
                ]
                
                for image_path in invite_images:
                    if self.find_and_click_element(image_path, confidence=0.7):
                        invite_button_found = True
                        break
                
                if invite_button_found:
                    # Проверяем успешность отправки
                    success_message_found = False
                    success_images = [
                        "images/success_message.png",
                        "images/invitations_sent.png",
                        "images/ok_message.png"
                    ]
                    
                    for image_path in success_images:
                        if self.find_and_click_element(image_path, confidence=0.7):
                            success_message_found = True
                            break
                    
                    if success_message_found:
                        self.logger.info(f"Группа пользователей {i//batch_size + 1} успешно приглашена")
                        for username in batch:
                            results[username] = True
                    else:
                        self.logger.warning(f"Не удалось подтвердить отправку приглашений для группы {i//batch_size + 1}")
                        # Пытаемся пригласить пользователей по одному
                        for username in batch:
                            try:
                                # Очищаем поле ввода
                                pyautogui.hotkey('ctrl', 'a')
                                pyautogui.press('delete')
                                self.random_delay()
                                
                                # Вводим одного пользователя
                                self.type_text(username)
                                self.random_delay()
                                
                                # Кликаем пригласить
                                if self.find_and_click_element("images/invite_button.png", confidence=0.7):
                                    results[username] = True
                                    self.logger.info(f"Пользователь {username} успешно приглашен")
                                else:
                                    results[username] = False
                                    self.logger.error(f"Не удалось пригласить пользователя {username}")
                                    
                            except Exception as e:
                                self.logger.error(f"Ошибка при приглашении пользователя {username}: {e}")
                                results[username] = False
                else:
                    self.logger.error("Кнопка приглашения не найдена")
                    for username in batch:
                        results[username] = False
                
                # Сохраняем промежуточные результаты
                self._save_results(results)
                
                # Закрываем окно приглашения после каждой группы
                try:
                    close_images = [
                        "images/close_button.png",
                        "images/x_button.png",
                        "images/close_window.png"
                    ]
                    
                    for image_path in close_images:
                        if self.find_and_click_element(image_path, confidence=0.7):
                            break
                    
                    self.random_delay()
                except:
                    pass
            
            return results
            
        except Exception as e:
            self.logger.error(f"Ошибка при приглашении пользователей в эфир: {e}")
            return {username: False for username in usernames}
    
    def _save_results(self, results: Dict[str, bool]):
        """Сохранение промежуточных результатов"""
        with open("desktop_inviter_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    
    def close(self):
        """Закрытие приложения"""
        try:
            # Закрываем TikTok Studio
            pyautogui.hotkey('alt', 'f4')
            self.random_delay()
            self.logger.info("TikTok Studio закрыт")
        except Exception as e:
            self.logger.error(f"Ошибка при закрытии TikTok Studio: {e}")


def create_sample_config():
    """Создание примера конфигурационного файла"""
    config = {
        "delay_range": [1, 3],
        "max_retries": 3,
        "timeout": 10,
        "tiktok_studio_path": "C:\\Program Files\\TikTok\\TikTok Studio.exe"
    }
    
    with open("tt_desktop_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print("Создан файл конфигурации tt_desktop_config.json")


def create_sample_usernames():
    """Создание примера списка пользователей"""
    usernames = [
        "example_user1",
        "example_user2", 
        "example_user3",
        "example_user4",
        "example_user5"
    ]
    
    with open("usernames.txt", "w", encoding="utf-8") as f:
        for username in usernames:
            f.write(f"{username}\n")
    
    print("Создан файл usernames.txt с примером списка пользователей")


def main():
    """Основная функция"""
    print("TikTok Studio Desktop Auto Inviter")
    print("=" * 50)
    
    # Проверяем наличие конфигурации
    try:
        with open("tt_desktop_config.json", "r") as f:
            json.load(f)
    except FileNotFoundError:
        print("Конфигурационный файл не найден. Создаем пример...")
        create_sample_config()
    
    # Проверяем наличие списка пользователей
    try:
        with open("usernames.txt", "r", encoding='utf-8') as f:
            usernames = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("Файл с никнеймами не найден. Создаем пример...")
        create_sample_usernames()
        usernames = []
    
    if not usernames:
        print("Список пользователей пуст. Пожалуйста, добавьте никнеймы в файл usernames.txt")
        return
    
    # Создаем инвайтер
    inviter = TikTokStudioDesktopInviter()
    
    try:
        # Запускаем TikTok Studio
        if not inviter.launch_tiktok_studio():
            print("Не удалось запустить TikTok Studio")
            return
        
        print(f"Начинаем приглашение {len(usernames)} пользователей...")
        
        # Приглашаем пользователей
        results = inviter.invite_users_to_stream(usernames)
        
        # Выводим результаты
        print("\nРезультаты приглашения:")
        print("-" * 30)
        success_count = 0
        for username, success in results.items():
            status = "✓ Успешно" if success else "✗ Неудачно"
            print(f"{username}: {status}")
            if success:
                success_count += 1
        
        print(f"\nВсего приглашено: {success_count}/{len(usernames)}")
        
    except Exception as e:
        print(f"Ошибка: {e}")
    finally:
        inviter.close()


if __name__ == "__main__":
    main()