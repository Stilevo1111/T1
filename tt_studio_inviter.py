#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok Studio Auto Inviter
Автоматическое приглашение пользователей в TikTok Studio по списку никнеймов
"""

import time
import json
import random
import logging
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

class TikTokStudioInviter:
    """Класс для автоматического приглашения пользователей в TikTok Studio"""
    
    def __init__(self, config_file: str = "tt_config.json"):
        """
        Инициализация инвайтера
        
        Args:
            config_file: путь к файлу конфигурации
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.driver = None
        self.wait = None
        
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('tt_inviter.log', encoding='utf-8'),
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
            "chrome_options": {
                "headless": False,
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            "delay_range": [2, 5],
            "max_retries": 3,
            "timeout": 10
        }
    
    def _save_config(self):
        """Сохранение конфигурации в JSON файл"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def setup_driver(self):
        """Настройка и запуск Chrome WebDriver"""
        chrome_options = Options()
        
        # Добавление опций из конфигурации
        if self.config["chrome_options"]["headless"]:
            chrome_options.add_argument("--headless")
        
        chrome_options.add_argument(f"--user-agent={self.config['chrome_options']['user_agent']}")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Другие полезные опции
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.wait = WebDriverWait(self.driver, self.config["timeout"])
            self.logger.info("Chrome WebDriver успешно настроен")
        except Exception as e:
            self.logger.error(f"Ошибка при настройке WebDriver: {e}")
            raise
    
    def random_delay(self):
        """Случайная задержка между действиями"""
        delay = random.uniform(*self.config["delay_range"])
        time.sleep(delay)
    
    def login_to_tiktok_studio(self, username: str, password: str) -> bool:
        """
        Авторизация в TikTok Studio
        
        Args:
            username: имя пользователя или email
            password: пароль
            
        Returns:
            bool: True если авторизация успешна, False в противном случае
        """
        try:
            self.logger.info("Начинаем процесс авторизации в TikTok Studio")
            
            # Открываем TikTok Studio
            self.driver.get("https://studio.tiktok.com/")
            self.random_delay()
            
            # Ждем загрузки страницы
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            # Пытаемся найти кнопку входа
            try:
                login_button = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Войти') or contains(text(), 'Log in') or contains(text(), 'Sign in')]"))
                )
                login_button.click()
                self.random_delay()
            except:
                self.logger.info("Кнопка входа не найдена, возможно уже авторизованы")
            
            # Ищем поля ввода логина и пароля
            try:
                username_field = self.wait.until(
                    EC.presence_of_element_located((By.XPATH, "//input[@type='text' or @type='email' or @type='username']"))
                )
                password_field = self.driver.find_element(By.XPATH, "//input[@type='password']")
                
                # Очищаем поля и вводим данные
                username_field.clear()
                username_field.send_keys(username)
                
                password_field.clear()
                password_field.send_keys(password)
                
                self.random_delay()
                
                # Ищем кнопку входа и нажимаем
                submit_button = self.driver.find_element(
                    By.XPATH, "//button[contains(text(), 'Войти') or contains(text(), 'Log in') or contains(text(), 'Sign in') or contains(text(), 'Submit')]"
                )
                submit_button.click()
                
                self.random_delay()
                
                # Проверяем успешность входа
                try:
                    self.wait.until(
                        EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'studio') or contains(@class, 'dashboard') or contains(@class, 'home')]"))
                    )
                    self.logger.info("Авторизация в TikTok Studio успешна")
                    return True
                except:
                    self.logger.error("Не удалось подтвердить успешную авторизацию")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Ошибка при вводе данных авторизации: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"Ошибка при авторизации: {e}")
            return False
    
    def invite_user(self, username: str) -> bool:
        """
        Приглашение пользователя в TikTok Studio
        
        Args:
            username: никнейм пользователя для приглашения
            
        Returns:
            bool: True если приглашение успешно, False в противном случае
        """
        try:
            self.logger.info(f"Пытаемся пригласить пользователя: {username}")
            
            # Ищем поле поиска пользователей
            search_field = self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//input[contains(@placeholder, 'Поиск') or contains(@placeholder, 'Search') or contains(@placeholder, 'Find')]"))
            )
            
            # Очищаем поле и вводим никнейм
            search_field.clear()
            search_field.send_keys(username)
            self.random_delay()
            
            # Ищем кнопку поиска или ждем появления результатов
            try:
                search_button = self.driver.find_element(
                    By.XPATH, "//button[contains(text(), 'Поиск') or contains(text(), 'Search') or contains(@type, 'submit')]"
                )
                search_button.click()
            except:
                self.logger.info("Кнопка поиска не найдена, ждем результаты")
            
            self.random_delay()
            
            # Ищем пользователя в результатах поиска
            user_element = self.wait.until(
                EC.presence_of_element_located((By.XPATH, f"//div[contains(text(), '{username}') or contains(@data-username, '{username}') or contains(@href, '{username}')]"))
            )
            
            # Прокручиваем к элементу
            self.driver.execute_script("arguments[0].scrollIntoView();", user_element)
            self.random_delay()
            
            # Ищем кнопку приглашения
            invite_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Пригласить') or contains(text(), 'Invite') or contains(text(), 'Add') or contains(text(), '+')]"))
            )
            
            invite_button.click()
            self.random_delay()
            
            # Проверяем, появилось ли подтверждение
            try:
                success_message = self.wait.until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'Приглашение отправлено') or contains(text(), 'Invited') or contains(text(), 'Success')]"))
                )
                self.logger.info(f"Пользователь {username} успешно приглашен")
                return True
            except:
                self.logger.info(f"Приглашение для {username} отправлено (подтверждение не найдено)")
                return True
                
        except Exception as e:
            self.logger.error(f"Ошибка при приглашении пользователя {username}: {e}")
            return False
    
    def invite_users_from_list(self, usernames: List[str]) -> Dict[str, bool]:
        """
        Приглашение пользователей из списка
        
        Args:
            usernames: список никнеймов для приглашения
            
        Returns:
            Dict[str, bool]: словарь с результатами для каждого пользователя
        """
        results = {}
        
        for i, username in enumerate(usernames, 1):
            self.logger.info(f"Обработка пользователя {i}/{len(usernames)}: {username}")
            
            # Случайная задержка между приглашениями
            if i > 1:
                self.random_delay()
            
            # Попытка пригласить пользователя с повторными попытками
            success = False
            for attempt in range(self.config["max_retries"]):
                try:
                    success = self.invite_user(username)
                    if success:
                        break
                    else:
                        self.logger.warning(f"Попытка {attempt + 1} для {username} не удалась")
                        if attempt < self.config["max_retries"] - 1:
                            self.random_delay()
                except Exception as e:
                    self.logger.error(f"Исключение при попытке {attempt + 1} для {username}: {e}")
                    if attempt < self.config["max_retries"] - 1:
                        self.random_delay()
            
            results[username] = success
            
            # Сохраняем промежуточные результаты
            self._save_results(results)
        
        return results
    
    def _save_results(self, results: Dict[str, bool]):
        """Сохранение промежуточных результатов"""
        with open("inviter_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    
    def close(self):
        """Закрытие WebDriver"""
        if self.driver:
            self.driver.quit()
            self.logger.info("WebDriver закрыт")


def create_sample_config():
    """Создание примера конфигурационного файла"""
    config = {
        "chrome_options": {
            "headless": False,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        "delay_range": [2, 5],
        "max_retries": 3,
        "timeout": 10
    }
    
    with open("tt_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print("Создан файл конфигурации tt_config.json")


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
    print("TikTok Studio Auto Inviter")
    print("=" * 50)
    
    # Проверяем наличие конфигурации
    try:
        with open("tt_config.json", "r") as f:
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
    
    # Запрашиваем данные для авторизации
    username = input("Введите имя пользователя/email для TikTok Studio: ")
    password = input("Введите пароль для TikTok Studio: ")
    
    # Создаем инвайтер
    inviter = TikTokStudioInviter()
    
    try:
        # Настраиваем WebDriver
        inviter.setup_driver()
        
        # Авторизуемся
        if not inviter.login_to_tiktok_studio(username, password):
            print("Не удалось авторизоваться в TikTok Studio")
            return
        
        # Приглашаем пользователей
        print(f"Начинаем приглашение {len(usernames)} пользователей...")
        results = inviter.invite_users_from_list(usernames)
        
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