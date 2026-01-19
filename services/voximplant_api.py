"""
Voximplant API с WebSocket для голосового ассистента.
Поддерживает стриминг ответов для более естественного диалога.
Динамическая база знаний + генерация приветствия + анализ результата.
"""

import json
import asyncio
import logging
import os
from typing import Dict, List, Optional
from contextlib import asynccontextmanager
from datetime import datetime

import requests
import httpx
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from openai import OpenAI

# SQLAlchemy для прямого сохранения в БД
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, update

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== Конфигурация ==============

OPENAI_API_KEY = "sk-vjg80yGvvHmzSlVPjLOGxWVvJywPf4yy"
OPENAI_BASE_URL = "https://api.proxyapi.ru/openai/v1"

VOXIMPLANT_CONFIG = {
    "account_id": "10046971",
    "api_key": "6dbf186a-2e15-4e55-a33f-d8ce05eef88e",
    "rule_id": "8106212",
}
load_dotenv(find_dotenv())
# Токен Telegram бота
TELEGRAM_BOT_TOKEN = os.getenv('TOKEN')  # ← Замени на свой токен

# База данных (та же что у бота)
DATABASE_URL = os.getenv('DB_URL')  # ← Укажи путь к своей БД

# Создаём engine и session_maker для БД
db_engine = create_async_engine(DATABASE_URL, echo=False)
db_session_maker = async_sessionmaker(db_engine, expire_on_commit=False)

# База знаний по умолчанию
DEFAULT_KNOWLEDGE_BASE = """
Acrelis — это динамичная IT-компания, специализирующаяся на разработке интеллектуальных решений для цифровизации бизнеса.
"""

# OpenAI клиент
client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


# Модели БД (копия из models.py)7838924584
# ============== Модели БД (копия из models.py) ==============
from sqlalchemy import Column, Integer, DateTime, String, Text, Boolean, BigInteger, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CallSession(Base):
    __tablename__ = "call_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    phone_numbers: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class CallResult(Base):
    __tablename__ = "call_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("call_sessions.id"))
    phone_number: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(50))
    interest_details: Mapped[str] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    call_duration: Mapped[int] = mapped_column(Integer, nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ============== Генерация приветствия ==============

def generate_greeting(knowledge_base: str) -> str:
    """
    Генерирует приветствие на основе базы знаний.
    Мы звоним клиенту и кратко представляемся.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """Ты помощник для генерации телефонных приветствий.
Сгенерируй ОЧЕНЬ короткое приветствие для исходящего звонка (мы звоним клиенту).

Правила:
- Максимум 1-2 предложения
- Назови компанию
- Кратко скажи чем занимается (буквально 3-5 слов)
- НЕ спрашивай "чем могу помочь" - мы звоним предложить услуги
- НЕ используй слова: "беспокоит", "отвлекаю"
- Тон: дружелюбный, профессиональный
- Только чистый текст без кавычек

Примеры хороших приветствий:
- "Добрый день! Компания ТехноСофт, занимаемся разработкой CRM-систем."
- "Здравствуйте! Это Акрелис, мы создаём IT-решения для бизнеса."
"""
                },
                {
                    "role": "user",
                    "content": f"База знаний о компании:\n{knowledge_base}\n\nСгенерируй приветствие:"
                }
            ],
            max_tokens=100,
            temperature=0.7,
        )

        greeting = response.choices[0].message.content.strip()
        # Убираем кавычки если есть
        greeting = greeting.strip('"\'')
        logger.info(f"Сгенерировано приветствие: {greeting}")
        return greeting

    except Exception as e:
        logger.error(f"Ошибка генерации приветствия: {e}")
        return "Добрый день! Звоню предложить вам наши услуги."


# ============== Анализ результата разговора ==============

def analyze_conversation(history: List[Dict[str, str]], knowledge_base: str) -> Dict:
    """
    Анализирует разговор и возвращает структурированный результат.
    """
    if not history:
        return {
            "status": "no_conversation",
            "interested": False,
            "interest_level": 0,
            "interested_services": [],
            "summary": "Разговор не состоялся",
            "next_action": "Перезвонить позже"
        }

    # Формируем текст разговора
    conversation_text = "\n".join([
        f"{'Клиент' if msg['role'] == 'user' else 'Менеджер'}: {msg['content']}"
        for msg in history
    ])

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """Ты аналитик телефонных разговоров. Проанализируй разговор и верни JSON.

Верни ТОЛЬКО валидный JSON без markdown, без ```json```, без пояснений:
{
    "status": "interested" | "not_interested" | "callback_requested" | "no_answer" | "busy",
    "interested": true | false,
    "interest_level": 1-10,
    "interested_services": ["услуга1", "услуга2"],
    "client_objections": ["возражение1"],
    "summary": "Краткий итог разговора в 1-2 предложения",
    "next_action": "Рекомендуемое следующее действие",
    "client_contact_info": "Если клиент оставил контакты"
}

Статусы:
- interested: клиент заинтересован, хочет узнать больше или купить
- not_interested: клиент отказался
- callback_requested: клиент попросил перезвонить позже
- no_answer: не ответил / бросил трубку
- busy: занят, не может говорить"""
                },
                {
                    "role": "user",
                    "content": f"""База знаний о компании:
{knowledge_base}

Разговор:
{conversation_text}

Проанализируй и верни JSON:"""
                }
            ],
            max_tokens=500,
            temperature=0.3,
        )

        result_text = response.choices[0].message.content.strip()

        # Убираем возможные markdown обёртки
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        result_text = result_text.strip()

        result = json.loads(result_text)
        logger.info(f"Результат анализа: {result}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON результата: {e}")
        return {
            "status": "error",
            "interested": False,
            "interest_level": 0,
            "interested_services": [],
            "summary": "Ошибка анализа разговора",
            "next_action": "Проверить вручную"
        }
    except Exception as e:
        logger.error(f"Ошибка анализа разговора: {e}")
        return {
            "status": "error",
            "interested": False,
            "interest_level": 0,
            "interested_services": [],
            "summary": f"Ошибка: {str(e)}",
            "next_action": "Проверить вручную"
        }


# ============== Сохранение результата в БД ==============

async def save_result_to_db(
        db_session_id: int,
        phone: str,
        result: Dict,
        call_duration: int = None
):
    """Сохраняет результат звонка напрямую в БД"""
    try:
        async with db_session_maker() as session:
            # Создаём запись результата
            call_result = CallResult(
                session_id=db_session_id,
                phone_number=phone,
                status=result.get("status", "unknown"),
                interest_details=", ".join(result.get("interested_services", [])) if result.get(
                    "interested_services") else None,
                notes=f"Итог: {result.get('summary', '')}\nРекомендация: {result.get('next_action', '')}",
                call_duration=call_duration
            )
            session.add(call_result)
            await session.commit()
            logger.info(f"✅ Результат сохранён в БД: {phone} -> {result.get('status')}")

            # Проверяем, все ли номера обработаны
            # Получаем сессию
            stmt = select(CallSession).where(CallSession.id == db_session_id)
            db_result = await session.execute(stmt)
            call_session = db_result.scalar_one_or_none()

            if call_session:
                phone_list = call_session.phone_numbers.split(",")

                # Считаем сколько результатов уже есть
                count_stmt = select(CallResult).where(CallResult.session_id == db_session_id)
                count_result = await session.execute(count_stmt)
                results_count = len(count_result.scalars().all())

                logger.info(f"Прогресс: {results_count}/{len(phone_list)} звонков")

                # Если все номера обработаны — меняем статус
                if results_count >= len(phone_list):
                    update_stmt = update(CallSession).where(
                        CallSession.id == db_session_id
                    ).values(
                        status="completed",
                        completed_at=datetime.utcnow()
                    )
                    await session.execute(update_stmt)
                    await session.commit()
                    logger.info(f"✅ Сессия {db_session_id} завершена!")

    except Exception as e:
        logger.error(f"❌ Ошибка сохранения в БД: {e}")


# ============== Отправка результата в Telegram ==============

def format_result_message(phone: str, result: Dict, history: List[Dict]) -> str:
    """Форматирует результат звонка для Telegram"""

    status_emoji = {
        "interested": "✅",
        "not_interested": "❌",
        "callback_requested": "📞",
        "no_answer": "📵",
        "busy": "📳",
        "declined": "🚫",
        "invalid_number": "❓",
        "error": "⚠️",
    }

    status_text = {
        "interested": "Заинтересован",
        "not_interested": "Не заинтересован",
        "callback_requested": "Просит перезвонить",
        "no_answer": "Не отвечает",
        "busy": "Занят",
        "declined": "Сбросил звонок",
        "invalid_number": "Неверный номер",
        "error": "Ошибка",
    }

    status = result.get("status", "unknown")
    emoji = status_emoji.get(status, "❓")
    status_ru = status_text.get(status, status)

    message = f"{emoji} <b>Результат звонка</b>\n\n"
    message += f"📱 <b>Телефон:</b> <code>{phone}</code>\n"
    message += f"📊 <b>Статус:</b> {status_ru}\n"

    # Для успешных звонков показываем детали
    if result.get("interested"):
        message += f"🔥 <b>Уровень интереса:</b> {result.get('interest_level', 0)}/10\n"

    services = result.get("interested_services", [])
    if services:
        message += f"🎯 <b>Интересующие услуги:</b> {', '.join(services)}\n"

    objections = result.get("client_objections", [])
    if objections:
        message += f"❗ <b>Возражения:</b> {', '.join(objections)}\n"

    # Для неудачных звонков показываем причину
    summary = result.get('summary', '-')
    if summary and summary != '-':
        message += f"\n📝 <b>Итог:</b> {summary}\n"

    next_action = result.get('next_action', '-')
    if next_action and next_action != '-':
        message += f"👉 <b>Рекомендация:</b> {next_action}\n"

    # Показываем количество реплик только если был разговор
    if len(history) > 0:
        message += f"\n💬 <b>Реплик в диалоге:</b> {len(history)}"

    return message


async def send_result_to_telegram(
        user_id: int,
        phone: str,
        result: Dict,
        history: List[Dict[str, str]],
        db_session_id: int = None
):
    """Сохраняет результат в БД и отправляет в Telegram"""

    # 1. Сохраняем в БД
    if db_session_id:
        await save_result_to_db(db_session_id, phone, result)

    # 2. Отправляем в Telegram
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        logger.warning("TELEGRAM_BOT_TOKEN не настроен!")
        return

    try:
        message = format_result_message(phone, result, history)

        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": user_id,
                    "text": message,
                    "parse_mode": "HTML"
                }
            )

            if response.status_code == 200:
                logger.info(f"Результат отправлен в Telegram: user_id={user_id}")
            else:
                logger.error(f"Ошибка Telegram API: {response.status_code}")

    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")


# ============== Построение системного промпта ==============

def build_system_prompt(knowledge_base: str) -> str:
    """Строит системный промпт для исходящего звонка"""
    return f"""Ты — менеджер по продажам, звонишь потенциальным клиентам.
Твоя задача — заинтересовать клиента услугами компании.

Информация о компании и услугах:
{knowledge_base}

Правила разговора:
- Отвечай кратко (1-2 предложения), это телефонный разговор
- Будь дружелюбным, но не навязчивым
- Если клиент не заинтересован — вежливо попрощайся
- Если клиент заинтересован — расскажи подробнее об услугах
- Если клиент просит перезвонить — уточни удобное время
- Если клиент спрашивает цену — дай примерный диапазон или предложи обсудить детали
- НЕ используй markdown, эмодзи и специальные символы
- Отвечай на русском языке
- Не будь роботом — общайся естественно

Если клиент говорит что занят или не может говорить:
- Спроси когда удобно перезвонить
- Поблагодари за время и попрощайся

Если клиент отказывается:
- Не настаивай
- Поблагодари за время
- Вежливо попрощайся

ВАЖНО: Когда прощаешься, обязательно используй слова: "до свидания", "всего доброго" или "хорошего дня".
"""


# ============== Детекция прощания ==============

def is_goodbye_message(text: str) -> bool:
    """Проверяет, является ли сообщение прощанием"""
    goodbye_phrases = [
        "до свидания", "досвидания", "до свиданья",
        "всего доброго", "всего хорошего",
        "хорошего дня", "удачного дня",
        "пока", "до встречи",
        "прощайте", "прощай",
        "счастливо", "удачи",
        "спасибо до свидания", "спасибо пока",
        "ладно пока", "ну пока",
        "всё пока", "все пока",
        "давай пока", "ну давай",
    ]
    text_lower = text.lower().strip()
    return any(phrase in text_lower for phrase in goodbye_phrases)


# ============== Управление сессиями ==============

class CallSession:
    """Сессия звонка с историей диалога"""

    def __init__(
            self,
            session_id: str,
            phone: str = "",
            knowledge_base: str = "",
            db_session_id: int = None,
            user_id: int = None  # ID пользователя Telegram
    ):
        self.session_id = session_id
        self.phone = phone
        self.knowledge_base = knowledge_base or DEFAULT_KNOWLEDGE_BASE
        self.db_session_id = db_session_id
        self.user_id = user_id  # Для отправки результата в Telegram
        self.history: List[Dict[str, str]] = []
        self.greeting: str = ""
        self.is_active = True

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content})

    def get_messages(self) -> List[Dict[str, str]]:
        system_prompt = build_system_prompt(self.knowledge_base)
        return [{"role": "system", "content": system_prompt}] + self.history


# Хранилище активных сессий
sessions: Dict[str, CallSession] = {}


def get_or_create_session(
        session_id: str,
        phone: str = "",
        knowledge_base: str = "",
        db_session_id: int = None,
        user_id: int = None
) -> CallSession:
    """Получить или создать сессию"""
    if session_id not in sessions:
        sessions[session_id] = CallSession(
            session_id, phone, knowledge_base, db_session_id, user_id
        )
        logger.info(f"Создана новая сессия: {session_id}")
    else:
        # Обновляем данные если переданы
        if knowledge_base:
            sessions[session_id].knowledge_base = knowledge_base
        if db_session_id:
            sessions[session_id].db_session_id = db_session_id
        if user_id:
            sessions[session_id].user_id = user_id
    return sessions[session_id]


def remove_session(session_id: str):
    """Удалить сессию"""
    if session_id in sessions:
        del sessions[session_id]
        logger.info(f"Сессия удалена: {session_id}")


# ============== Генерация ответов ==============

def generate_reply(session: CallSession, user_text: str) -> str:
    """Генерирует полный ответ (без стриминга)"""
    session.add_message("user", user_text)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=session.get_messages(),
            max_tokens=150,
            temperature=0.7,
        )

        reply = response.choices[0].message.content
        session.add_message("assistant", reply)

        return reply

    except Exception as e:
        logger.error(f"Ошибка OpenAI: {e}")
        return "Извините, плохо слышно. Можете повторить?"


async def generate_reply_stream(session: CallSession, user_text: str):
    """Генерирует ответ с стримингом по предложениям"""
    session.add_message("user", user_text)

    full_reply = ""
    buffer = ""
    sentence_endings = ".!?"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=session.get_messages(),
            max_tokens=150,
            temperature=0.7,
            stream=True,
        )

        for chunk in response:
            try:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta is not None and hasattr(delta, 'content') and delta.content:
                        text = delta.content
                        full_reply += text
                        buffer += text

                        while any(end in buffer for end in sentence_endings):
                            for i, char in enumerate(buffer):
                                if char in sentence_endings:
                                    sentence = buffer[:i + 1].strip()
                                    if sentence:
                                        yield sentence
                                    buffer = buffer[i + 1:].lstrip()
                                    break
            except (IndexError, AttributeError) as e:
                logger.debug(f"Пропущен chunk: {e}")
                continue

        if buffer.strip():
            yield buffer.strip()

        if full_reply:
            session.add_message("assistant", full_reply)

    except Exception as e:
        logger.error(f"Ошибка OpenAI stream: {e}")
        yield "Извините, плохо слышно. Можете повторить?"


# ============== FastAPI приложение ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Сервер запущен")
    yield
    logger.info("Сервер остановлен")


app = FastAPI(title="Voximplant Voice Assistant", lifespan=lifespan)


class CallRequest(BaseModel):
    phone: str
    knowledge_base: Optional[str] = None
    greeting: Optional[str] = None
    db_session_id: Optional[int] = None  # ID сессии в БД Telegram бота
    user_id: Optional[int] = None  # ID пользователя Telegram для отправки результата


class SpeechRequest(BaseModel):
    text: str
    session_id: Optional[str] = "default"


# ============== WebSocket эндпоинт ==============

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket эндпоинт для Voximplant"""
    await websocket.accept()

    session: Optional[CallSession] = None
    session_id = "ws_" + str(id(websocket))

    logger.info(f"WebSocket подключён: {session_id}")

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type", "")

            logger.info(f"[{session_id}] Получено: {msg_type}")

            if msg_type == "init":
                # Инициализация сессии
                phone = message.get("phone", "")
                knowledge_base = message.get("knowledge_base", "")
                custom_greeting = message.get("greeting", "")
                db_session_id = message.get("db_session_id")
                user_id = message.get("user_id")  # ID пользователя Telegram
                custom_session_id = message.get("session_id", session_id)

                session = get_or_create_session(
                    custom_session_id,
                    phone,
                    knowledge_base,
                    db_session_id,
                    user_id
                )
                session_id = custom_session_id

                # Генерируем приветствие на основе базы знаний
                if custom_greeting:
                    greeting = custom_greeting
                elif knowledge_base:
                    greeting = generate_greeting(knowledge_base)
                else:
                    greeting = "Добрый день! Звоню предложить вам наши услуги."

                session.greeting = greeting
                session.add_message("assistant", greeting)

                await websocket.send_text(json.dumps({
                    "type": "greeting",
                    "text": greeting
                }))
                logger.info(f"[{session_id}] Приветствие: {greeting}")

            elif msg_type == "speech":
                text = message.get("text", "").strip()
                if not text:
                    continue

                if session is None:
                    session = get_or_create_session(session_id)

                logger.info(f"[{session_id}] Клиент: {text}")

                # Генерируем ответ
                full_response = ""
                async for chunk in generate_reply_stream(session, text):
                    await websocket.send_text(json.dumps({
                        "type": "chunk",
                        "text": chunk
                    }))
                    full_response += chunk + " "
                    logger.info(f"[{session_id}] Менеджер: {chunk}")

                await websocket.send_text(json.dumps({"type": "done"}))

                # Проверяем, попрощались ли обе стороны
                client_said_goodbye = is_goodbye_message(text)
                bot_said_goodbye = is_goodbye_message(full_response)

                if client_said_goodbye and bot_said_goodbye:
                    logger.info(f"[{session_id}] Обе стороны попрощались, завершаем звонок")

                    # Небольшая пауза чтобы бот успел договорить
                    await asyncio.sleep(2)

                    # Отправляем сигнал завершения
                    await websocket.send_text(json.dumps({
                        "type": "hangup",
                        "reason": "goodbye"
                    }))

                    # Анализируем и сохраняем результат
                    if session:
                        result = analyze_conversation(session.history, session.knowledge_base)
                        logger.info(f"[{session_id}] Результат: {result}")

                        if session.user_id:
                            await send_result_to_telegram(
                                user_id=session.user_id,
                                phone=session.phone,
                                result=result,
                                history=session.history,
                                db_session_id=session.db_session_id
                            )

                        await websocket.send_text(json.dumps({
                            "type": "result",
                            "data": result
                        }))

                    remove_session(session_id)
                    break

            elif msg_type == "call_failed":
                # Звонок не удался (не ответил, занят, и т.д.)
                status = message.get("status", "no_answer")
                reason = message.get("reason", "Неизвестная причина")

                logger.info(f"[{session_id}] Звонок не удался: {status} - {reason}")

                if session:
                    # Формируем результат
                    result = {
                        "status": status,
                        "interested": False,
                        "interest_level": 0,
                        "interested_services": [],
                        "summary": reason,
                        "next_action": "Перезвонить позже",
                        "client_objections": []
                    }

                    # Отправляем в Telegram и сохраняем в БД
                    if session.user_id:
                        await send_result_to_telegram(
                            user_id=session.user_id,
                            phone=session.phone,
                            result=result,
                            history=[],
                            db_session_id=session.db_session_id
                        )

            elif msg_type == "end":
                logger.info(f"[{session_id}] Звонок завершён")

                if session:
                    # Анализируем разговор
                    result = analyze_conversation(session.history, session.knowledge_base)
                    logger.info(f"[{session_id}] Результат: {result}")

                    # Отправляем результат в Telegram
                    if session.user_id:
                        await send_result_to_telegram(
                            user_id=session.user_id,
                            phone=session.phone,
                            result=result,
                            history=session.history,
                            db_session_id=session.db_session_id
                        )

                    # Отправляем результат обратно в Voximplant (опционально)
                    await websocket.send_text(json.dumps({
                        "type": "result",
                        "data": result
                    }))

                remove_session(session_id)
                break

    except WebSocketDisconnect:
        logger.info(f"[{session_id}] WebSocket отключён")
        # Результат уже отправлен в msg_type == "end", просто очищаем сессию
        remove_session(session_id)
    except Exception as e:
        logger.error(f"[{session_id}] Ошибка WebSocket: {e}")
        remove_session(session_id)


# ============== HTTP эндпоинты ==============

@app.post("/call")
def make_call(
        phone: Optional[str] = None,
        knowledge_base: Optional[str] = None,
        greeting: Optional[str] = None,
        db_session_id: Optional[int] = None,
        user_id: Optional[int] = None,
        request: Optional[CallRequest] = None
):
    """Инициировать исходящий звонок через Voximplant"""

    # Поддержка обоих вариантов
    if request:
        phone = request.phone or phone
        knowledge_base = request.knowledge_base or knowledge_base
        greeting = request.greeting or greeting
        db_session_id = request.db_session_id or db_session_id
        user_id = request.user_id or user_id

    if not phone:
        return {"status": "error", "message": "Phone number required"}

    # Создаём сессию
    session_id = f"call_{phone}_{db_session_id or 'default'}"
    get_or_create_session(session_id, phone, knowledge_base or "", db_session_id, user_id)

    # Данные для Voximplant сценария
    script_data = {
        "phone": phone,
        "session_id": session_id,
    }

    if knowledge_base:
        script_data["knowledge_base"] = knowledge_base
    if greeting:
        script_data["greeting"] = greeting
    if db_session_id:
        script_data["db_session_id"] = db_session_id
    if user_id:
        script_data["user_id"] = user_id

    response = requests.post(
        "https://api.voximplant.com/platform_api/StartScenarios",
        params={
            "account_id": VOXIMPLANT_CONFIG["account_id"],
            "api_key": VOXIMPLANT_CONFIG["api_key"],
            "rule_id": VOXIMPLANT_CONFIG["rule_id"],
            "script_custom_data": json.dumps(script_data),
        },
    )

    result = response.json()
    logger.info(f"StartScenarios: {result}")

    return {
        "status": "ok" if "result" in result else "error",
        "session_id": session_id,
        "voximplant_response": result,
    }


@app.post("/speech")
def speech_http(request: SpeechRequest):
    """HTTP fallback для обработки речи"""
    session = get_or_create_session(request.session_id)
    reply = generate_reply(session, request.text)
    return {"status": "ok", "reply": reply}


@app.post("/end_call")
def end_call(session_id: str = "default"):
    """Завершить сессию"""
    remove_session(session_id)
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "active_sessions": len(sessions)}


@app.get("/sessions")
def list_sessions():
    return {
        "count": len(sessions),
        "sessions": [
            {
                "id": s.session_id,
                "phone": s.phone,
                "messages": len(s.history),
                "db_session_id": s.db_session_id,
            }
            for s in sessions.values()
        ]
    }


# ============== Сохранение результата в БД ==============

class SaveResultRequest(BaseModel):
    """Запрос на сохранение результата звонка"""
    db_session_id: int
    phone: str
    status: str
    interested_services: Optional[List[str]] = None
    summary: Optional[str] = None
    next_action: Optional[str] = None


@app.post("/save_result")
async def save_call_result(request: SaveResultRequest):
    """
    Сохраняет результат звонка.
    Этот endpoint вызывается после анализа разговора.
    """
    logger.info(f"Сохранение результата: {request.phone} -> {request.status}")

    # Результат сохраняется через Telegram бота
    # Здесь просто логируем
    return {
        "status": "ok",
        "message": "Result logged",
        "data": request.dict()
    }


# ============== Запуск ==============

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=1111)