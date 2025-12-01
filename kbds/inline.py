# inline.py
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_inlineMix_btns(
        *,
        btns: dict[str, str],
        sizes: tuple[int] = (2,)
) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    for text, data in btns.items():
        keyboard.add(InlineKeyboardButton(text=text, callback_data=data))

    return keyboard.adjust(*sizes).as_markup()
