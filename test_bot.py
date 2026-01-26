"""Тестовый файл для проверки работоспособности бота"""

import asyncio
import logging
from config import BOT_TOKEN, validate_config
from database import init_db, get_user, update_user
from game_logic import calculate_character_stats, get_fissure_result

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_bot_components():
    """Тестирование основных компонентов бота"""
    try:
        # 1. Проверка конфигурации
        logger.info("🔍 Проверка конфигурации...")
        if not validate_config():
            logger.error("❌ Конфигурация не прошла валидацию")
            return False
        logger.info("✅ Конфигурация валидна")
        
        # 2. Проверка подключения к базе данных
        logger.info("🔍 Проверка подключения к базе данных...")
        try:
            # Создаем фиктивное приложение для теста
            class MockApp:
                pass
            
            await init_db(MockApp())
            logger.info("✅ Подключение к базе данных установлено")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к базе данных: {e}")
            return False
        
        # 3. Тестирование создания пользователя
        logger.info("🔍 Тестирование создания пользователя...")
        try:
            test_user = get_user(123456, "TestUser")
            # Handle both sync (SQLite) and async (PostgreSQL) results
            if hasattr(test_user, '__await__'):
                test_user = await test_user
            if test_user and 'username' in test_user:
                logger.info("✅ Пользователь успешно создан/получен")
            else:
                logger.error("❌ Не удалось создать/получить пользователя")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка создания пользователя: {e}")
            return False

        # 4. Тестирование расчета характеристик
        logger.info("🔍 Тестирование расчета характеристик...")
        try:
            stats = calculate_character_stats(test_user)
            required_stats = ['max_hp', 'base_damage', 'dodge_chance', 'crit_chance']
            for stat in required_stats:
                if stat not in stats:
                    logger.error(f"❌ Отсутствует характеристика: {stat}")
                    return False
            logger.info("✅ Расчет характеристик работает корректно")
        except Exception as e:
            logger.error(f"❌ Ошибка расчета характеристик: {e}")
            return False

        # 5. Тестирование FISSURE системы
        logger.info("🔍 Тестирование FISSURE системы...")
        try:
            fissure_value, text, phrase = get_fissure_result()
            if isinstance(fissure_value, (int, float)) and fissure_value > 0:
                logger.info("✅ FISSURE система работает корректно")
            else:
                logger.error("❌ Ошибка в FISSURE системе")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка FISSURE системы: {e}")
            return False

        # 6. Тестирование обновления пользователя
        logger.info("🔍 Тестирование обновления пользователя...")
        try:
            update_result = update_user(123456, gold=500, exp=100)
            # Handle both sync (SQLite) and async (PostgreSQL) results
            if hasattr(update_result, '__await__'):
                await update_result

            updated_user = get_user(123456, "TestUser")
            if hasattr(updated_user, '__await__'):
                updated_user = await updated_user

            if updated_user['gold'] == 500 and updated_user['exp'] == 100:
                logger.info("✅ Обновление пользователя работает корректно")
            else:
                logger.error("❌ Ошибка обновления пользователя")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка обновления пользователя: {e}")
            return False
        
        logger.info("🎉 Все тесты пройдены успешно!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при тестировании: {e}")
        return False

async def main():
    """Главная функция тестирования"""
    logger.info("🚀 Запуск тестирования бота...")
    success = await test_bot_components()
    if success:
        logger.info("✅ Тестирование завершено успешно")
    else:
        logger.error("❌ Тестирование завершено с ошибками")
    return success

if __name__ == "__main__":
    # Запуск тестирования
    result = asyncio.run(main())
    exit(0 if result else 1)