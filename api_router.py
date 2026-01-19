# api_router.py
"""
FastAPI роутер для API endpoints бота.
Принимает результаты звонков от Voximplant API.

Подключение в main.py:
    from api_router import api_router, setup_api
    from fastapi import FastAPI

    # Создаём FastAPI app
    api_app = FastAPI()
    api_app.include_router(api_router)

    # В on_startup:
    setup_api(session_maker)

    # Запускаем в отдельном потоке или через hypercorn/uvicorn
"""

import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/api", tags=["api"])

# Глобальная переменная для session_maker
_session_maker = None


def setup_api(session_maker):
    """Инициализация API с session_maker из бота"""
    global _session_maker
    _session_maker = session_maker
    logger.info("API router initialized")


class SaveCallResultRequest(BaseModel):
    """Запрос на сохранение результата звонка"""
    session_id: int
    phone: str
    status: str
    interest_details: Optional[str] = None
    notes: Optional[str] = None


class UpdateSessionStatusRequest(BaseModel):
    """Запрос на обновление статуса сессии"""
    session_id: int
    status: str


@api_router.post("/save_call_result")
async def save_call_result(request: SaveCallResultRequest):
    """
    Сохраняет результат звонка в БД.
    Вызывается из voximplant_api_ws.py после анализа разговора.
    """
    if not _session_maker:
        raise HTTPException(status_code=500, detail="Database not configured")

    try:
        from database.orm_query import orm_create_call_result, orm_get_session_by_id, orm_update_session, \
            orm_get_session_results

        async with _session_maker() as session:
            # Сохраняем результат звонка
            result_data = {
                "session_id": request.session_id,
                "phone_number": request.phone,
                "status": request.status,
                "interest_details": request.interest_details,
                "notes": request.notes,
            }

            await orm_create_call_result(session, result_data)
            logger.info(f"Результат сохранён: {request.phone} -> {request.status}")

            # Проверяем, все ли номера обработаны
            call_session = await orm_get_session_by_id(session, request.session_id)
            if call_session:
                phone_list = call_session.phone_numbers.split(",")
                results = await orm_get_session_results(session, request.session_id)

                # Если все номера обработаны — меняем статус на completed
                if len(results) >= len(phone_list):
                    await orm_update_session(session, request.session_id, {
                        "status": "completed",
                        "completed_at": datetime.utcnow()
                    })
                    logger.info(f"Сессия {request.session_id} завершена (все номера обработаны)")

            return {"status": "ok", "message": "Result saved"}

    except Exception as e:
        logger.error(f"Ошибка сохранения результата: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/update_session_status")
async def update_session_status(request: UpdateSessionStatusRequest):
    """Обновляет статус сессии"""
    if not _session_maker:
        raise HTTPException(status_code=500, detail="Database not configured")

    try:
        from database.orm_query import orm_update_session

        async with _session_maker() as session:
            update_data = {"status": request.status}
            if request.status == "completed":
                update_data["completed_at"] = datetime.utcnow()

            await orm_update_session(session, request.session_id, update_data)
            logger.info(f"Статус сессии {request.session_id} обновлён: {request.status}")

            return {"status": "ok"}

    except Exception as e:
        logger.error(f"Ошибка обновления статуса: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/health")
async def health():
    """Health check"""
    return {"status": "ok", "db_configured": _session_maker is not None}