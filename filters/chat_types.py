from aiogram.filters import Filter
from aiogram import Bot, types


class ChatTypeFilter(Filter):
    def __init__(self, chat_types: list[str]) -> None:
        self.chat_types = chat_types

    async def __call__(self, message: types.Message) -> bool:
        return message.chat.type in self.chat_types


class IsAdmin(Filter):
    def __init__(self) -> None:
        pass

    async def __call__(self, message: types.Message, bot: Bot) -> bool:
        # Используем список админов из бота, который заполняется в user_group.py
        if hasattr(bot, 'my_admins_list') and bot.my_admins_list:
            return message.from_user.id in bot.my_admins_list
        return False