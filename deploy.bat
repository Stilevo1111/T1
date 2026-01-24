@echo off
echo ========================================
echo Загрузка исправлений в GitHub...
echo ========================================
echo.

REM Проверка наличия git
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo ОШИБКА: Git не найден в системе!
    echo Установите Git: https://git-scm.com/download/win
    pause
    exit /b 1
)

REM Проверка, что мы в git репозитории
git status >nul 2>&1
if %errorlevel% neq 0 (
    echo ОШИБКА: Это не git репозиторий!
    echo Инициализируйте репозиторий: git init
    pause
    exit /b 1
)

REM Проверка настроек Git (имя и email)
git config user.name >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ВНИМАНИЕ: Git не настроен!
    echo Настраиваю Git с временными значениями...
    git config user.name "Fissure Bot"
    git config user.email "fissure-bot@noreply.github.com"
    echo Готово! Используются временные настройки.
    echo.
    echo Если хотите использовать свои данные, выполните:
    echo   git config --global user.name "Ваше имя"
    echo   git config --global user.email "ваш@email.com"
    echo.
)

echo Проверка текущего статуса...
git status

echo.
echo Добавление файлов...
git add requirements.txt runtime.txt bot.py README.md .env.example .gitignore deploy.bat DEPLOY_INSTRUCTIONS.md QUICK_FIX.md GIT_COMMANDS.txt

echo.
echo Создание коммита...
git commit -m "Исправлен requirements.txt: заменен aiogram на pyTelegramBotAPI для деплоя на Render"

if %errorlevel% neq 0 (
    echo.
    echo ВНИМАНИЕ: Коммит не создан. Возможно, нет изменений для коммита.
    echo Проверьте статус: git status
    pause
    exit /b 1
)

echo.
echo Отправка в GitHub...
git push origin main

if %errorlevel% neq 0 (
    echo.
    echo ОШИБКА при отправке в GitHub!
    echo Проверьте настройки удаленного репозитория: git remote -v
    pause
    exit /b 1
)

echo.
echo ========================================
echo Готово! Изменения отправлены в GitHub.
echo.
echo Теперь:
echo 1. Перейдите на Render.com
echo 2. Дождитесь автоматического деплоя (или запустите вручную)
echo 3. Проверьте логи - должно быть "Collecting pyTelegramBotAPI"
echo ========================================
pause
