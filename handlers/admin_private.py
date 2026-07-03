import asyncio
from datetime import datetime

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from database.orm_query import (
    orm_get_user, orm_create_user, orm_create_call_session,
    orm_get_user_sessions, orm_get_session_by_id, orm_update_session,
    orm_delete_session, parse_phone_numbers, orm_get_session_results,
    orm_delete_user_sessions_by_status
)
from filters.chat_types import ChatTypeFilter, IsAdmin

admin_router = Router()
admin_router.message.filter(ChatTypeFilter(["private"]), IsAdmin())


class CallSessionStates(StatesGroup):
    waiting_for_phones = State()
    waiting_for_knowledge = State()
    confirming_start = State()


# ===== KEYBOARDS =====
def get_main_keyboard():
    """Главное меню - только 2 кнопки"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📞 Новый обзвон", callback_data="input_numbers")],
        ]
    )


def get_back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]
        ]
    )


def get_confirm_start_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Начать обзвон", callback_data="confirm_start")],
            [InlineKeyboardButton(text="↩️ Отмена", callback_data="main_menu")]
        ]
    )


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
        "👋 <b>Добро пожаловать в бот для обзвона!</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


@admin_router.message(Command("admin"))
async def admin_command(message: Message, session: AsyncSession):
    await message.answer(
        "⚙️ <b>Админ панель</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


# ===== CALLBACK HANDLERS =====
@admin_router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👋 <b>Добро пожаловать в бот для обзвона!</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data == "input_numbers")
async def input_numbers_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CallSessionStates.waiting_for_phones)
    await callback.message.edit_text(
        "📞 <b>Введите номера телефонов</b>\n\n"
        "Через пробел или каждый с новой строки:\n\n"
        "<code>+79161234567 84951234567</code>\n\n"
        "Поддерживаемые форматы:\n"
        "• +7 916 123-45-67\n"
        "• 8 (916) 123-45-67\n"
        "• 79161234567",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode="HTML"
    )


# ===== PAST SESSIONS =====
@admin_router.callback_query(F.data == "past_sessions")
async def past_sessions_callback(callback: CallbackQuery, session: AsyncSession):
    """Показывает список прошлых сеансов с датами"""
    user_id = callback.from_user.id
    completed_sessions = await orm_get_user_sessions(session, user_id, status="completed")

    if not completed_sessions:
        await callback.message.edit_text(
            "📊 <b>Прошлые сеансы</b>\n\n"
            "У вас пока нет завершённых сеансов обзвона.",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode="HTML"
        )
        return

    # Формируем кнопки с датами сеансов
    buttons = []
    for sess in completed_sessions[:10]:  # Максимум 10 сеансов
        # Формат: "29.12 10:00 (5 номеров)"
        phone_count = len(sess.phone_numbers.split(',')) if sess.phone_numbers else 0
        date_str = sess.created.strftime('%d.%m %H:%M')
        button_text = f"📅 {date_str} ({phone_count} ном.)"
        buttons.append([InlineKeyboardButton(
            text=button_text,
            callback_data=f"view_session_{sess.id}"
        )])

    # Добавляем кнопку удаления всех и возврата в меню
    if len(completed_sessions) > 0:
        buttons.append([InlineKeyboardButton(
            text="🗑 Удалить все сеансы",
            callback_data="delete_all_past"
        )])
    buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")])

    await callback.message.edit_text(
        f"📊 <b>Прошлые сеансы</b>\n\n"
        f"Всего завершённых: {len(completed_sessions)}\n"
        f"Выберите сеанс для просмотра результатов:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data.startswith("view_session_"))
async def view_session_results(callback: CallbackQuery, session: AsyncSession):
    """Показывает результаты конкретного сеанса"""
    session_id = int(callback.data.split("_")[2])
    call_session = await orm_get_session_by_id(session, session_id)

    if not call_session:
        await callback.answer("Сеанс не найден")
        return

    # Получаем результаты звонков
    results = await orm_get_session_results(session, session_id)

    # Считаем статистику
    total = len(results)
    interested = sum(1 for r in results if r.status == "interested")
    not_interested = sum(1 for r in results if r.status == "not_interested")
    callback_requested = sum(1 for r in results if r.status == "callback_requested")
    no_answer = sum(1 for r in results if r.status in ["no_answer", "busy", "error"])

    # Формируем текст результатов
    text = f"📊 <b>Результаты сеанса</b>\n"
    text += f"📅 {call_session.created.strftime('%d.%m.%Y %H:%M')}\n\n"

    # Статистика
    text += f"📞 <b>Всего звонков:</b> {total}\n"
    if total > 0:
        text += f"✅ Заинтересованы: {interested} ({interested / total * 100:.0f}%)\n"
        text += f"❌ Отказы: {not_interested}\n"
        text += f"📞 Перезвонить: {callback_requested}\n"
        text += f"📵 Не ответили: {no_answer}\n"

    # Детали по каждому звонку
    if results:
        text += "\n<b>Детали:</b>\n"

        status_emoji = {
            "interested": "✅",
            "not_interested": "❌",
            "callback_requested": "📞",
            "no_answer": "📵",
            "busy": "⏳",
            "error": "⚠️",
        }

        for r in results[:15]:  # Максимум 15 результатов чтобы не превысить лимит
            emoji = status_emoji.get(r.status, "❓")
            text += f"\n{emoji} <code>{r.phone_number}</code>"
            if r.interest_details:
                text += f"\n   🎯 {r.interest_details[:50]}"
            if r.notes:
                # Извлекаем краткий итог из notes
                notes_lines = r.notes.split('\n')
                for line in notes_lines:
                    if line.startswith("Итог:"):
                        summary = line.replace("Итог:", "").strip()[:60]
                        text += f"\n   📝 {summary}"
                        break
    else:
        text += "\n<i>Результаты звонков пока не получены</i>"

    # Кнопки
    buttons = [
        [InlineKeyboardButton(text="🗑 Удалить сеанс", callback_data=f"delete_session_{session_id}")],
        [InlineKeyboardButton(text="↩️ К списку сеансов", callback_data="past_sessions")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data == "delete_all_past")
async def delete_all_past_callback(callback: CallbackQuery, session: AsyncSession):
    """Удаляет все прошлые сеансы"""
    user_id = callback.from_user.id

    deleted = await orm_delete_user_sessions_by_status(
        session=session,
        user_id=user_id,
        statuses=["completed"]
    )

    await callback.message.edit_text(
        f"🗑 <b>Удалено сеансов:</b> {deleted}\n\n"
        "Все прошлые сеансы очищены.",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data.startswith("delete_session_"))
async def delete_session(callback: CallbackQuery, session: AsyncSession):
    """Удаляет конкретный сеанс"""
    session_id = int(callback.data.split("_")[2])

    success = await orm_delete_session(session, session_id)
    if success:
        await callback.message.edit_text(
            "✅ Сеанс успешно удалён",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ К списку сеансов", callback_data="past_sessions")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]
            ]),
            parse_mode="HTML"
        )
    else:
        await callback.answer("Ошибка при удалении сеанса")


# ===== STATE HANDLERS =====
@admin_router.message(CallSessionStates.waiting_for_phones)
async def process_phone_numbers(message: Message, state: FSMContext, session: AsyncSession):
    phone_text = message.text
    phones = parse_phone_numbers(phone_text)

    if not phones:
        await message.answer(
            "❌ Не удалось распознать номера телефонов.\n\n"
            "Пожалуйста, введите номера через пробел:",
            reply_markup=get_back_to_menu_keyboard()
        )
        return

    await state.update_data(phone_numbers=phones, phone_text=phone_text)
    await state.set_state(CallSessionStates.waiting_for_knowledge)

    await message.answer(
        f"✅ Распознано номеров: {len(phones)}\n\n"
        "📚 <b>Теперь введите информацию о компании</b>\n\n"
        "Напишите:\n"
        "• Название компании\n"
        "• Какие услуги/товары предлагаете\n"
        "• Контактные данные\n"
        "• Любую другую важную информацию",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode="HTML"
    )


@admin_router.message(CallSessionStates.waiting_for_knowledge)
async def process_knowledge_base(message: Message, state: FSMContext, session: AsyncSession):
    knowledge_base = message.text
    data = await state.get_data()

    # Создаем сеанс сразу со статусом draft
    session_data = {
        "user_id": message.from_user.id,
        "phone_numbers": ",".join(data['phone_numbers']),
        "knowledge_base": knowledge_base,
        "status": "draft",
        "name": f"Сеанс от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    }

    call_session = await orm_create_call_session(session, session_data)

    await state.update_data(
        knowledge_base=knowledge_base,
        draft_session_id=call_session.id
    )
    await state.set_state(CallSessionStates.confirming_start)

    phone_count = len(data['phone_numbers'])
    phones_preview = ", ".join(data['phone_numbers'][:3])
    if phone_count > 3:
        phones_preview += f" и ещё {phone_count - 3}"

    await message.answer(
        f"📋 <b>Проверьте данные:</b>\n\n"
        f"📞 <b>Номера ({phone_count}):</b>\n<code>{phones_preview}</code>\n\n"
        f"📚 <b>О компании:</b>\n{knowledge_base[:200]}{'...' if len(knowledge_base) > 200 else ''}\n\n"
        f"Начать обзвон?",
        reply_markup=get_confirm_start_keyboard(),
        parse_mode="HTML",
    )


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
        f"🚀 <b>Обзвон запущен!</b>\n\n"
        f"📞 Номеров: {len(phones)}\n"
        f"⏳ Статус: выполняется\n\n"
        "Результаты каждого звонка будут приходить сюда.\n"
        "Итоговая статистика — в разделе «Прошлые сеансы».",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode="HTML"
    )

    # Запускаем звонки с базой знаний и user_id
    asyncio.create_task(
        run_call_campaign(
            session_id=session_id,
            phones=phones,
            knowledge_base=knowledge_base,
            user_id=callback.from_user.id
        )
    )


# ===== CALL FUNCTIONS =====
async def run_call_campaign(session_id: int, phones: list, knowledge_base: str, user_id: int):
    """
    Запускает кампанию обзвона.
    Обзванивает все номера последовательно.
    Статус сессии обновляется автоматически через API после каждого звонка.
    """
    for i, phone in enumerate(phones):
        try:
            print(f"📞 Звонок {i + 1}/{len(phones)}: {phone}")
            await initiate_call_to_api(
                phone=phone,
                knowledge_base=knowledge_base,
                db_session_id=session_id,
                user_id=user_id
            )
            # Пауза между звонками (ждём завершения текущего)
            # Звонок длится ~30-60 секунд
            await asyncio.sleep(45)
        except Exception as e:
            print(f"❌ Ошибка при звонке на {phone}: {e}")

    print(f"✅ Кампания {session_id} завершена: {len(phones)} звонков")


async def initiate_call_to_api(
        phone: str,
        knowledge_base: str = "",
        db_session_id: int = None,
        user_id: int = None,
        greeting: str = None
):
    """
    Инициирует звонок через FastAPI эндпоинт.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            call_data = {
                "phone": phone,
                "knowledge_base": knowledge_base,
                "db_session_id": db_session_id,
                "user_id": user_id,
            }

            if greeting:
                call_data["greeting"] = greeting

            response = await client.post(
                "https://neiroagent007.ru/call",
                json=call_data
            )

            if response.status_code == 200:
                result = response.json()
                print(f"✅ Звонок на {phone} инициирован: {result}")
                return result
            else:
                print(f"❌ Ошибка при звонке на {phone}: {response.status_code} - {response.text}")
                return None

    except Exception as e:
        print(f"❌ Ошибка подключения к API: {e}")
        return None