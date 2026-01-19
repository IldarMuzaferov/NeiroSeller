# main.py
"""
Главный файл Telegram бота для обзвона.
"""

import asyncio
import logging

from create_bot import dp, bot
from handlers.admin_private import admin_router
from handlers.user_private import user_private_router
from handlers.user_group import user_group_router
from middlewares.db import DataBaseSession
from database.engine import create_db, drop_db, session_maker

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Привязываем session_maker к боту
bot.session_maker = session_maker

# Подключаем роутеры бота
dp.include_router(admin_router)
dp.include_router(user_private_router)
dp.include_router(user_group_router)



async def on_startup():
    run_param = False
    if run_param:
        await drop_db()
    await create_db()
    logger.info("База данных инициализирована")


async def main():
    # Регистрируем startup
    dp.startup.register(on_startup)
    dp.update.middleware(DataBaseSession(session_pool=session_maker))

    # Удаляем старые webhook
    await bot.delete_webhook(drop_pending_updates=True)

    # Запускаем polling бота
    logger.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")