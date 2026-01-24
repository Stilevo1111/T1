# Инструкция по деплою на Render

## Проблема
На GitHub в репозитории все еще старая версия `requirements.txt` с `aiogram`, а локально используется `pyTelegramBotAPI`.

## Решение

### Вариант 1: Автоматический (рекомендуется)
Просто запустите файл `deploy.bat` двойным кликом. Он автоматически:
- Добавит все нужные файлы в git
- Создаст коммит
- Отправит изменения в GitHub

### Вариант 2: Вручную через терминал
Откройте терминал в папке проекта и выполните:

```bash
cd c:\Users\akado\fissure-bot
git add requirements.txt runtime.txt bot.py README.md .env.example .gitignore
git commit -m "Исправлен requirements.txt: заменен aiogram на pyTelegramBotAPI"
git push origin main
```

## После пуша в GitHub

1. **Перейдите на Render.com** в настройки вашего сервиса
2. **Проверьте настройки:**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
   - Environment Variables: добавьте `BOT_TOKEN` со значением вашего токена
3. **Запустите новый деплой** (Render должен сделать это автоматически)

## Проверка

После деплоя проверьте логи. Должно быть:
- ✅ `Collecting pyTelegramBotAPI==4.14.0`
- ❌ НЕ должно быть `Collecting aiogram`

Если все правильно, бот успешно запустится!
