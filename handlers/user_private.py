import asyncio
import os
import tempfile
from aiogram import F, Router, types
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, FSInputFile, ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton, \
    InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

# from database.orm_query import
from filters.chat_types import IsAdmin

user_private_router = Router()
user_private_router.message.filter(F.chat.type == "private")