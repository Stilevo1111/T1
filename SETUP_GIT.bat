@echo off
echo ========================================
echo Настройка Git для проекта
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

echo Введите ваше имя для Git (или нажмите Enter для пропуска):
set /p GIT_NAME="Имя: "

echo.
echo Введите ваш email для Git (или нажмите Enter для пропуска):
set /p GIT_EMAIL="Email: "

if not "%GIT_NAME%"=="" (
    git config user.name "%GIT_NAME%"
    echo Имя установлено: %GIT_NAME%
)

if not "%GIT_EMAIL%"=="" (
    git config user.email "%GIT_EMAIL%"
    echo Email установлен: %GIT_EMAIL%
)

if "%GIT_NAME%"=="" if "%GIT_EMAIL%"=="" (
    echo.
    echo Используются временные настройки для этого репозитория.
    git config user.name "Fissure Bot"
    git config user.email "fissure-bot@noreply.github.com"
    echo.
    echo Если хотите настроить глобально для всех проектов, выполните:
    echo   git config --global user.name "Ваше имя"
    echo   git config --global user.email "ваш@email.com"
)

echo.
echo ========================================
echo Настройка завершена!
echo Теперь можно запустить deploy.bat
echo ========================================
pause
