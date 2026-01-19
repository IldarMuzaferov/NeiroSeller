# orm_query.py
from sqlalchemy import select, delete, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Tuple
import logging
import re
from database.models import CallSession, CallResult, User

logger = logging.getLogger(__name__)


# ===== USER OPERATIONS =====
async def orm_get_user(session: AsyncSession, user_id: int) -> Optional[User]:
    query = select(User).where(User.id == user_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def orm_create_user(session: AsyncSession, user_data: dict) -> User:
    user = User(**user_data)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def orm_update_user(session: AsyncSession, user_id: int, data: dict) -> Optional[User]:
    query = update(User).where(User.id == user_id).values(**data)
    await session.execute(query)
    await session.commit()
    return await orm_get_user(session, user_id)


# ===== CALL SESSION OPERATIONS =====
async def orm_create_call_session(session: AsyncSession, session_data: dict) -> CallSession:
    call_session = CallSession(**session_data)
    session.add(call_session)
    await session.commit()
    await session.refresh(call_session)
    return call_session


async def orm_get_user_sessions(session: AsyncSession, user_id: int, status: str = None) -> List[CallSession]:
    query = select(CallSession).where(CallSession.user_id == user_id)
    if status:
        query = query.where(CallSession.status == status)
    query = query.order_by(CallSession.created.desc())
    result = await session.execute(query)
    return result.scalars().all()


async def orm_get_session_by_id(session: AsyncSession, session_id: int) -> Optional[CallSession]:
    query = select(CallSession).where(CallSession.id == session_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def orm_update_session(session: AsyncSession, session_id: int, data: dict) -> Optional[CallSession]:
    query = update(CallSession).where(CallSession.id == session_id).values(**data)
    await session.execute(query)
    await session.commit()
    return await orm_get_session_by_id(session, session_id)


async def orm_delete_session(session: AsyncSession, session_id: int) -> bool:
    """
    Удаляет сеанс и все связанные с ним CallResult.
    """
    # Сначала удаляем результаты звонков
    delete_results = delete(CallResult).where(CallResult.session_id == session_id)
    await session.execute(delete_results)

    # Затем удаляем сам сеанс
    delete_session_q = delete(CallSession).where(CallSession.id == session_id)
    await session.execute(delete_session_q)

    await session.commit()
    return True


# ===== CALL RESULT OPERATIONS =====
async def orm_create_call_result(session: AsyncSession, result_data: dict) -> CallResult:
    call_result = CallResult(**result_data)
    session.add(call_result)
    await session.commit()
    await session.refresh(call_result)
    return call_result


async def orm_get_session_results(session: AsyncSession, session_id: int) -> List[CallResult]:
    query = select(CallResult).where(CallResult.session_id == session_id)
    result = await session.execute(query)
    return result.scalars().all()


# ===== UTILITY FUNCTIONS =====



def parse_phone_numbers(phone_text: str) -> List[str]:
    """Парсит номера телефонов из текста"""
    phones = phone_text.split()
    normalized_phones = [phone for phone in phones]
    return [phone for phone in normalized_phones if len(phone) >= 10]

async def orm_get_all_user_sessions(session: AsyncSession, user_id: int) -> List[CallSession]:
    """Получает все сеансы пользователя"""
    query = select(CallSession).where(CallSession.user_id == user_id)
    query = query.order_by(CallSession.created.desc())
    result = await session.execute(query)
    return result.scalars().all()


async def orm_delete_user_sessions_by_status(
    session: AsyncSession,
    user_id: int,
    statuses: List[str]
) -> int:
    """
    Удаляет все сеансы пользователя с указанными статусами.
    Возвращает количество удалённых сеансов.
    """
    query = select(CallSession.id).where(
        CallSession.user_id == user_id,
        CallSession.status.in_(statuses)
    )
    result = await session.execute(query)
    session_ids = result.scalars().all()

    deleted = 0
    from database.orm_query import orm_delete_session  # если функция в этом же файле, импорт не нужен

    for sid in session_ids:
        await orm_delete_session(session, sid)
        deleted += 1

    return deleted