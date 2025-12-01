import re
from string import punctuation

from aiogram import Bot, types, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command

from filters.chat_types import ChatTypeFilter

user_group_router = Router()
user_group_router.message.filter(ChatTypeFilter(["group", "supergroup"]))
user_group_router.edited_message.filter(ChatTypeFilter(["group", "supergroup"]))


@user_group_router.message(Command("admin"))
async def get_admins(message: types.Message, bot: Bot):
    chat_id = message.chat.id
    admins_list = await bot.get_chat_administrators(chat_id)
    admins_list = [
        member.user.id
        for member in admins_list
        if member.status == "creator" or member.status == "administrator"
    ]
    bot.my_admins_list = admins_list

    print(admins_list)


def clean_text(text: str):
    return text.translate(str.maketrans("", "", punctuation))


async def send_order_to_group(bot: Bot, group_id: int, order_info: str):
    await bot.send_message(chat_id=group_id, text=order_info)
