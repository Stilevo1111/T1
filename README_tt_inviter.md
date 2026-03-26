# TikTok Studio Auto Inviter

Программа для автоматического приглашения пользователей в TikTok Studio по списку никнеймов.

## Функциональность

- Автоматическая авторизация в TikTok Studio
- Приглашение пользователей по списку никнеймов
- Настройка задержек и повторных попыток
- Логирование процесса
- Сохранение промежуточных результатов

## Требования

- Python 3.8+
- Chrome WebDriver
- Библиотеки: selenium, json, time, random, logging

## Установка

1. Установите зависимости:
```bash
pip install selenium
```

2. Скачайте Chrome WebDriver и добавьте его в PATH:
   - [Скачать Chrome WebDriver](https://chromedriver.chromium.org/)

## Использование

1. Запустите программу:
```bash
python tt_studio_inviter.py
```

2. Программа создаст файлы конфигурации и пример списка пользователей

3. Отредактируйте файлы:
   - `tt_config.json` - настройки браузера и задержек
   - `usernames.txt` - список никнеймов для приглашения (по одному на строку)

4. Введите данные для авторизации в TikTok Studio

## Конфигурация

Файл `tt_config.json` содержит настройки:

```json
{
  "chrome_options": {
    "headless": false,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
  },
  "delay_range": [2, 5],
  "max_retries": 3,
  "timeout": 10
}
```

Параметры:
- `headless`: запуск браузера в фоновом режиме
- `user_agent`: User-Agent строки для браузера
- `delay_range`: диапазон случайных задержек между действиями (в секундах)
- `max_retries`: максимальное количество попыток для каждого действия
- `timeout`: таймаут ожидания элементов (в секундах)

## Формат списка пользователей

Файл `usernames.txt` должен содержать никнеймы по одному на строку:

```
user1
user2
user3
```

## Логирование

Программа создает лог-файл `tt_inviter.log` с подробной информацией о процессе.

## Результаты

Промежуточные результаты сохраняются в `inviter_results.json` в формате:
```json
{
  "username1": true,
  "username2": false
}
```

## Важные замечания

- Программа использует Selenium для автоматизации браузера
- Рекомендуется использовать случайные задержки для избежания блокировок
- Программа не обходит капчи и другие системы защиты
- Используйте на свой страх и риск, соблюдайте правила TikTok Studio

## Пример использования

```python
from tt_studio_inviter import TikTokStudioInviter

# Создаем инвайтер
inviter = TikTokStudioInviter()

try:
    # Настраиваем браузер
    inviter.setup_driver()
    
    # Авторизуемся
    inviter.login_to_tiktok_studio("username", "password")
    
    # Приглашаем пользователей
    usernames = ["user1", "user2", "user3"]
    results = inviter.invite_users_from_list(usernames)
    
    print(f"Приглашено: {sum(results.values())}/{len(results)}")
    
finally:
    inviter.close()
```

## Лицензия

Этот проект предоставляется как есть, без гарантий. Используйте на свой страх и риск.