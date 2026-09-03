"""
Точка входа: запуск Telegram-бота модератора.
"""

import sys
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import config
from database import db
from handlers.commands import router as commands_router
from handlers.admin import router as admin_router
from handlers.moderation import router as moderation_router


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    )
    logger = logging.getLogger("ChatModeratorBot")

    if not config.bot_token or config.bot_token == "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz":
        logger.error(
            "❌ BOT_TOKEN не установлен в файле .env!\n"
            "Пожалуйста, создайте файл .env на основе .env.example и вставьте токен от @BotFather."
        )
        sys.exit(1)

    # Инициализация базы данных
    logger.info("Инициализация базы данных SQLite...")
    await db.init_db()

    # Инициализация бота
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Подключение роутеров:
    # 1. Админ-команды
    # 2. Пользовательские команды (/score, /rules, /top)
    # 3. Модерация всех остальных сообщений
    dp.include_router(admin_router)
    dp.include_router(commands_router)
    dp.include_router(moderation_router)

    # Запуск бота
    logger.info("Запуск бота модератора классного чата...")
    try:
        # Удаляем вебхуки и пропускаем старые апдейты
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
