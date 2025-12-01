import asyncio
import tempfile
from datetime import datetime

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from database.orm_query import (
    orm_get_user, orm_create_user, orm_create_call_session,
    orm_get_user_sessions, orm_get_session_by_id, orm_update_session,
    orm_delete_session, parse_phone_numbers, orm_get_session_results, orm_delete_user_sessions_by_status
)
from filters.chat_types import ChatTypeFilter, IsAdmin
from services.uis_client import run_uis_campaign


admin_router = Router()
admin_router.message.filter(ChatTypeFilter(["private"]), IsAdmin())


class CallSessionStates(StatesGroup):
    waiting_for_phones = State()
    waiting_for_knowledge = State()
    confirming_start = State()


# ===== KEYBOARDS =====
def get_main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📞 Ввести номера", callback_data="input_numbers")],
            [InlineKeyboardButton(text="📊 Прошлые сеансы", callback_data="past_sessions")],
            [InlineKeyboardButton(text="⏳ Незаконченные сеансы", callback_data="unfinished_sessions")]
        ]
    )


def get_back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Меню", callback_data="main_menu")]
        ]
    )


def get_confirm_start_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="confirm_start")],
            [InlineKeyboardButton(text="↩️ Меню", callback_data="main_menu")]
        ]
    )


def get_session_actions_keyboard(session_id: int, session_status: str = "draft"):
    """Клавиатура действий для сеанса"""
    buttons = []

    if session_status == "draft":
        # Для черновиков - продолжить и удалить
        buttons.append([InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"continue_session_{session_id}")])
        buttons.append([InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_session_{session_id}")])
    elif session_status == "active":
        # Для активных сеансов - только просмотр статуса (или ничего)
        buttons.append([InlineKeyboardButton(text="📊 Посмотреть статус", callback_data=f"view_status_{session_id}")])
    else:
        # Для завершенных - просмотр результатов
        buttons.append(
            [InlineKeyboardButton(text="📈 Посмотреть результаты", callback_data=f"view_results_{session_id}")])

    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="unfinished_sessions")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ===== MAIN HANDLERS =====
@admin_router.message(Command("start"))
async def start_command(message: Message, session: AsyncSession):
    user = await orm_get_user(session, message.from_user.id)
    if not user:
        user_data = {
            "id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "is_admin": True
        }
        await orm_create_user(session, user_data)

    await message.answer(
        "👋 Добро пожаловать в бот для обзвона!\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )


@admin_router.message(Command("admin"))
async def admin_command(message: Message, session: AsyncSession):
    await message.answer(
        "⚙️ Админ панель:",
        reply_markup=get_main_keyboard()
    )


# ===== CALLBACK HANDLERS =====
@admin_router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👋 Добро пожаловать в бот для обзвона!\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )


@admin_router.callback_query(F.data == "input_numbers")
async def input_numbers_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CallSessionStates.waiting_for_phones)
    await callback.message.edit_text(
        "📞 Введите номера телефонов через пробел:\n\n"
        "Пример: +79161234567 84951234567 88002000600\n\n"
        "Номера могут быть в форматах:\n"
        "• +7 916 123-45-67\n"
        "• 8 (916) 123-45-67\n"
        "• 79161234567",
        reply_markup=get_back_to_menu_keyboard()
    )


@admin_router.callback_query(F.data == "past_sessions")
async def past_sessions_callback(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    completed_sessions = await orm_get_user_sessions(session, user_id, status="completed")

    if not completed_sessions:
        await callback.message.edit_text(
            "📊 У вас пока нет завершенных сеансов.",
            reply_markup=get_back_to_menu_keyboard()
        )
        return

    text = "📊 Ваши прошлые сеансы:\n\n"
    for sess in completed_sessions:
        text += f"• Сеанс #{sess.id} - {sess.created.strftime('%d.%m.%Y %H:%M')}\n"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                                [InlineKeyboardButton(text=f"Сеанс #{sess.id}",
                                                      callback_data=f"view_session_{sess.id}")]
                                for sess in completed_sessions[:5]  # Ограничиваем 5 сеансами
                            ] + [[InlineKeyboardButton(text="🗑 Удалить все прошлые", callback_data="delete_all_past")]] + [[InlineKeyboardButton(text="↩️ Назад", callback_data="main_menu")]]
        )
    )

@admin_router.callback_query(F.data == "delete_all_past")
async def delete_all_past_callback(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id

    deleted = await orm_delete_user_sessions_by_status(
        session=session,
        user_id=user_id,
        statuses=["completed"]   # или как у тебя называется завершённый сеанс
    )

    await callback.message.edit_text(
        f"Удалено прошлых сеансов: {deleted}.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
            ]
        )
    )

@admin_router.callback_query(F.data == "unfinished_sessions")
async def unfinished_sessions_callback(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    # Ищем сеансы со статусами "draft" (черновик) и "active" (активные)
    unfinished_sessions = await orm_get_user_sessions(session, user_id)
    unfinished_sessions = [s for s in unfinished_sessions if s.status in ["draft", "active"]]

    if not unfinished_sessions:
        await callback.message.edit_text(
            "⏳ У вас нет незаконченных сеансов.",
            reply_markup=get_back_to_menu_keyboard()
        )
        return

    text = "⏳ Ваши незаконченные сеансы:\n\n"
    for sess in unfinished_sessions:
        status_text = "Черновик" if sess.status == "draft" else "Активный"
        text += f"• Сеанс #{sess.id} - {sess.created.strftime('%d.%m.%Y %H:%M')} ({status_text})\n"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                                [InlineKeyboardButton(
                                    text=f"Сеанс #{sess.id} ({'Черновик' if sess.status == 'draft' else 'Активный'})",
                                    callback_data=f"view_unfinished_{sess.id}")]
                                for sess in unfinished_sessions[:5]
                            ] + [[InlineKeyboardButton(text="🗑 Удалить все незаконченные", callback_data="delete_all_unfinished")]] + [[InlineKeyboardButton(text="↩️ Назад", callback_data="main_menu")]]
        )
    )
@admin_router.callback_query(F.data.startswith("view_session_"))
async def view_session(callback: CallbackQuery, session: AsyncSession):
    session_id = int(callback.data.split("_")[2])
    call_session = await orm_get_session_by_id(session, session_id)

    if not call_session:
        await callback.answer("Сеанс не найден")
        return

    results = await orm_get_session_results(session, session_id)
    total = len(results)
    interested = sum(1 for r in results if r.status == "interested")
    not_interested = sum(1 for r in results if r.status == "not_interested")
    operator_req = sum(1 for r in results if r.status == "operator_request")
    errors = sum(1 for r in results if r.status == "error")

    text_lines = [
        f"📊 Сеанс #{call_session.id}",
        f"📅 Создан: {call_session.created.strftime('%d.%m.%Y %H:%M')}",
        f"🔚 Завершён: {call_session.completed_at.strftime('%d.%m.%Y %H:%M') if call_session.completed_at else '—'}",
        "",
        f"Всего звонков: {total}",
        f"✅ Заинтересовались: {interested}",
        f"⚪️ Не заинтересованы: {not_interested}",
        f"📞 Попросили оператора: {operator_req}",
        f"❌ Ошибки/проблемы: {errors}",
        "",
        "Детали по номерам:"
    ]

    # подробный список номеров
    for r in results[:20]:  # ограничим вывод первыми 20 для читаемости
        line = f"• {r.phone_number} — {r.status}"
        if r.interest_details:
            line += f" ({r.interest_details[:60] + '…' if len(r.interest_details) > 60 else r.interest_details})"
        text_lines.append(line)

    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="Удалить сеанс",
                    callback_data=f"delete_session_{call_session.id}"
                )],
                [InlineKeyboardButton(text="↩️ Назад", callback_data="past_sessions")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
            ]
        )
    )

@admin_router.callback_query(F.data == "delete_all_unfinished")
async def delete_all_unfinished_callback(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id

    # считаем незаконченные = draft + active (подстрой под свои статусы)
    deleted = await orm_delete_user_sessions_by_status(
        session=session,
        user_id=user_id,
        statuses=["draft", "active"]
    )

    await callback.message.edit_text(
        f"Удалено незаконченных сеансов: {deleted}.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
            ]
        )
    )

@admin_router.callback_query(F.data.startswith("delete_session_"))
async def delete_session_callback(callback: CallbackQuery, session: AsyncSession):
    session_id = int(callback.data.split("_")[2])

    await orm_delete_session(session, session_id)

    await callback.message.edit_text(
        f"Сеанс #{session_id} удалён.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")],
            ]
        )
    )


# Кнопка "📈 Посмотреть результаты" из блока незаконченных сеансов
@admin_router.callback_query(F.data.startswith("view_results_"))
async def view_results(callback: CallbackQuery, session: AsyncSession):
    # просто переиспользуем тот же хендлер
    callback.data = callback.data.replace("view_results_", "view_session_")
    await view_session(callback, session)


# Кнопка "📊 Посмотреть статус" для активного сеанса
@admin_router.callback_query(F.data.startswith("view_status_"))
async def view_status(callback: CallbackQuery, session: AsyncSession):
    session_id = int(callback.data.split("_")[2])
    call_session = await orm_get_session_by_id(session, session_id)

    if not call_session:
        await callback.answer("Сеанс не найден")
        return

    results = await orm_get_session_results(session, session_id)
    total_numbers = len(call_session.phone_numbers.split(","))
    done = len(results)

    text = (
        f"🔄 Статус сеанса #{session_id}\n\n"
        f"Всего номеров: {total_numbers}\n"
        f"Уже обработано: {done}\n"
        f"Статус сеанса: {call_session.status}\n"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Назад", callback_data="unfinished_sessions")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
            ]
        )
    )
# ===== STATE HANDLERS =====
@admin_router.message(CallSessionStates.waiting_for_phones)
async def process_phone_numbers(message: Message, state: FSMContext, session: AsyncSession):
    phone_text = message.text
    phones = parse_phone_numbers(phone_text)

    if not phones:
        await message.answer(
            "❌ Не удалось распознать номера телефонов. "
            "Пожалуйста, введите номера через пробел:",
            reply_markup=get_back_to_menu_keyboard()
        )
        return

    await state.update_data(phone_numbers=phones, phone_text=phone_text)
    await state.set_state(CallSessionStates.waiting_for_knowledge)

    await message.answer(
        "📚 Теперь введите базу знаний (название компании, услуги, описание):",
        reply_markup=get_back_to_menu_keyboard()
    )


@admin_router.message(CallSessionStates.waiting_for_knowledge)
async def process_knowledge_base(message: Message, state: FSMContext, session: AsyncSession):
    knowledge_base = message.text
    data = await state.get_data()

    # Создаем черновик сеанса
    session_data = {
        "user_id": message.from_user.id,
        "phone_numbers": ",".join(data['phone_numbers']),
        "knowledge_base": knowledge_base,
        "status": "draft",  # Черновик
        "name": f"Сеанс от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    }

    call_session = await orm_create_call_session(session, session_data)

    await state.update_data(
        knowledge_base=knowledge_base,
        draft_session_id=call_session.id
    )
    await state.set_state(CallSessionStates.confirming_start)

    phone_count = len(data['phone_numbers'])

    await message.answer(
        f"📋 Проверьте данные:\n\n"
        f"📞 Номера: <code>{call_session.phone_numbers}</code>\n"
        f"📚 База знаний: {knowledge_base[:100]}{'...' if len(knowledge_base) > 100 else ''}\n\n"
        f"Начать обзвон?",
        reply_markup=get_confirm_start_keyboard(),
        parse_mode="HTML",
    )

# ===== SESSION MANAGEMENT HANDLERS =====
@admin_router.callback_query(F.data.startswith("view_unfinished_"))
async def view_unfinished_session(callback: CallbackQuery, session: AsyncSession):
    session_id = int(callback.data.split("_")[2])
    call_session = await orm_get_session_by_id(session, session_id)

    if not call_session:
        await callback.answer("Сеанс не найден")
        return

    phone_count = len(call_session.phone_numbers.split(','))

    await callback.message.edit_text(
        f"⏳ Незаконченный сеанс #{session_id}\n\n"
        f"📞 Номера: <code>{call_session.phone_numbers}</code>\n"
        f"📚 База знаний: {call_session.knowledge_base[:200]}{'...' if len(call_session.knowledge_base) > 200 else ''}\n"
        f"📅 Создан: {call_session.created.strftime('%d.%m.%Y %H:%M')}\n"
        f"🔄 Статус: {'Черновик' if call_session.status == 'draft' else 'Активный'}",
        reply_markup=get_session_actions_keyboard(session_id, call_session.status),
        parse_mode="HTML"
    )

@admin_router.callback_query(F.data.startswith("continue_session_"))
async def continue_session(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    session_id = int(callback.data.split("_")[2])
    call_session = await orm_get_session_by_id(session, session_id)

    if not call_session:
        await callback.answer("Сеанс не найден")
        return

    await state.update_data(
        phone_numbers=call_session.phone_numbers.split(','),
        knowledge_base=call_session.knowledge_base,
        existing_session_id=session_id
    )
    await state.set_state(CallSessionStates.confirming_start)

    phone_count = len(call_session.phone_numbers.split(','))

    await callback.message.edit_text(
        f"📋 Продолжение сеанса #{session_id}:\n\n"
        f"📞 Номера: <code>{call_session.phone_numbers}</code>\n"
        f"📚 База знаний: {call_session.knowledge_base[:100]}{'...' if len(call_session.knowledge_base) > 100 else ''}\n\n"
        f"Начать обзвон?",
        reply_markup=get_confirm_start_keyboard(),
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data.startswith("delete_session_"))
async def delete_session(callback: CallbackQuery, session: AsyncSession):
    session_id = int(callback.data.split("_")[2])

    success = await orm_delete_session(session, session_id)
    if success:
        await callback.message.edit_text(
            "✅ Сеанс успешно удален",
            reply_markup=get_back_to_menu_keyboard()
        )
    else:
        await callback.answer("Ошибка при удалении сеанса")


@admin_router.callback_query(F.data == "confirm_start")
async def confirm_start_callback(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()

    session_data = {
        "status": "active",
        "started_at": datetime.utcnow()
    }

    # Определяем ID сеанса
    if 'draft_session_id' in data:
        await orm_update_session(session, data['draft_session_id'], session_data)
        session_id = data['draft_session_id']
    elif 'existing_session_id' in data:
        await orm_update_session(session, data['existing_session_id'], session_data)
        session_id = data['existing_session_id']
    else:
        new_session_data = {
            "user_id": callback.from_user.id,
            "phone_numbers": ",".join(data['phone_numbers']),
            "knowledge_base": data['knowledge_base'],
            "status": "active",
            "started_at": datetime.utcnow(),
            "name": f"Сеанс от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        }
        call_session = await orm_create_call_session(session, new_session_data)
        session_id = call_session.id

    phones = data["phone_numbers"]
    knowledge_base = data["knowledge_base"]

    await state.clear()

    await callback.message.edit_text(
        f"🚀 Начинаем обзвон сеанса #{session_id}!\n\n"
        f"📞 Номера: {len(phones)} шт.\n"
        f"⏳ Статус: запускается.\n\n"
        "Результаты будут доступны в разделе «Прошлые сеансы».",
        reply_markup=get_back_to_menu_keyboard()
    )

    # Стартуем кампанию в фоне, чтобы не блокировать обработчик Telegram
    asyncio.create_task(
        run_uis_campaign(call_session_id=session_id, phones=phones, knowledge_base=knowledge_base)
    )


