# uis_client.py
import os
import aiohttp
import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv

from create_bot import bot
from database.orm_query import (
    orm_update_session,
    orm_create_call_result,
)
from database.orm_query import normalize_phone_number

logger = logging.getLogger(__name__)
load_dotenv(dotenv_path="D:\project\CallSeller\.env")

UIS_API_URL = "https://callapi.uiscom.ru/v4.0"
UIS_ACCESS_TOKEN = os.getenv("UIS_ACCESS_TOKEN")  # ты уже получил и настроил
UIS_VIRTUAL_PHONE = os.getenv("UIS_VIRTUAL_PHONE")    # номер/линию из UIS, с которой звоним


async def _uis_call_start(phone: str, text: str, external_id: str | None = None) -> dict:
    """Один запрос start.informer_call к UIS."""
    if not UIS_ACCESS_TOKEN:
        raise RuntimeError("UIS_ACCESS_TOKEN не задан в переменных окружения")

    if not UIS_VIRTUAL_PHONE:
        raise RuntimeError("UIS_VIRTUAL_PHONE не задан в переменных окружения")

    payload = {
        "jsonrpc": "2.0",
        "id": "req1",
        "method": "start.informer_call",
        "params": {
            "access_token": UIS_ACCESS_TOKEN,
            "virtual_phone_number": UIS_VIRTUAL_PHONE,
            "contact": phone,
            "direction": "out",
            "dialing_timeout": 25,
            "external_id": external_id or phone,
            "contact_message": {
                "type": "tts",
                "value": text
            }
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(UIS_API_URL, json=payload, timeout=30) as resp:
            status = resp.status
            data = await resp.json(content_type=None)
            logger.info("=== UIS CALL DEBUG START ===")
            logger.info("→ HTTP статус: %s", status)
            logger.info("→ Ответ UIS: %s", data)
            logger.info("=== UIS CALL DEBUG END ===")
            if "error" in data:
                raise RuntimeError(str(data["error"]))
            return data.get("result", {}).get("data", {})

async def run_uis_campaign(call_session_id: int, phones: list[str], knowledge_base: str):
    """
    Полноценный запуск обзвона:
    - идём по списку телефонов
    - по каждому вызываем UIS TTS-обзвон
    - пишем результат в таблицу CallResult
    - по завершении проставляем статус сеанса = completed
    """
    logger.info("[UIS] Старт кампании, session_id=%s, phones=%s", call_session_id, phones)

    # Текст для TTS — сейчас простой, на базе knowledge_base
    # потом сможешь подставить сюда текст из YandexGPT
    base_text = (
        "Здравствуйте! Вас беспокоит нейро-продавец компании Ildar "
        "Мы работаем со следующими услугами: чесать писю и попу. А также после наших услуг вы будете себя чувствовать грусненько"
        f"{knowledge_base[:250]}..."
        " Если вам интересно, дождитесь звонка менеджера. Спасибо!"
    )

    # Открываем свою сессию БД через bot.session_maker (см. main.py)
    async with bot.session_maker() as db_session:
        # Обновляем статус: на всякий случай
        await orm_update_session(db_session, call_session_id, {
            "status": "active",
            "started_at": datetime.utcnow()
        })

        for raw_phone in phones:
            phone = normalize_phone_number(raw_phone)
            logger.info("[UIS] Стартовал звонок. session_id=%s, phone=%s", call_session_id, phone)

            status = "error"
            notes = ""
            try:
                result = await _uis_call_start(
                    phone=phone,
                    text=base_text,
                    external_id=f"session_{call_session_id}_{phone}",
                )
                call_session_id_uis = result.get("call_session_id")
                notes = f"UIS call_session_id={call_session_id_uis}"
                status = "completed"   # пока просто факт дозвона/запуска сценария
            except Exception as e:
                logger.exception("[UIS] Ошибка звонка на %s", phone)
                notes = f"Ошибка UIS: {e}"
                status = "error"

            # Сохраняем результат по номеру
            await orm_create_call_result(db_session, {
                "session_id": call_session_id,
                "phone_number": phone,
                "status": status,          # interested/not_interested/operator_request/no_answer/... — пока просто completed/error
                "interest_details": None,  # позже сюда положишь разбор нейросети
                "notes": notes,
                "call_duration": None      # при желании возьмёшь из статистики UIS
            })

            # небольшая пауза между звонками, чтобы не долбить API
            await asyncio.sleep(2)

        # Кампания завершена — помечаем сеанс как completed
        await orm_update_session(db_session, call_session_id, {
            "status": "completed",
            "completed_at": datetime.utcnow()
        })

    logger.info("=== UIS кампания завершена (session %s) ===", call_session_id)
