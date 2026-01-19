import os
import json
import asyncio
import logging
import re
from typing import Optional, Dict, Any, List

import aiohttp

logger = logging.getLogger(__name__)

VOX_API_BASE = "https://api.voximplant.com/platform_api"

VOX_API_KEY = os.getenv("VOXIMPLANT_API_KEY")
VOX_ACCOUNT_ID = os.getenv("VOXIMPLANT_ACCOUNT_ID")
VOX_ACCOUNT_NAME = os.getenv("VOXIMPLANT_ACCOUNT_NAME")
VOX_RULE_ID = os.getenv("VOXIMPLANT_RULE_ID")

# FastAPI
PUBLIC_BACKEND_URL = os.getenv("PUBLIC_BACKEND_URL")

DEFAULT_CALLER_ID = os.getenv("VOXIMPLANT_CALLER_ID")


def _require_env(name: str, value: Optional[str]) -> str:
    if not value:
        raise RuntimeError(f"ENV {name} is required")
    return value

def to_e164_ru(phone: str) -> str:
    p = re.sub(r"\D+", "", phone)
    if p.startswith("8") and len(p) == 11:
        p = "7" + p[1:]
    if p.startswith("7") and len(p) == 11:
        return "+" + p
    if p.startswith("9") and len(p) == 10:
        return "+7" + p
    return "+" + p if not p.startswith("+") else p
async def _start_scenario(phone: str, call_session_id: int, knowledge_base: str) -> Dict[str, Any]:
    api_key = _require_env("VOXIMPLANT_API_KEY", VOX_API_KEY)
    rule_id = _require_env("VOXIMPLANT_RULE_ID", VOX_RULE_ID)


    params = {"api_key": api_key}
    if VOX_ACCOUNT_ID:
        params["account_id"] = VOX_ACCOUNT_ID
    elif VOX_ACCOUNT_NAME:
        params["account_name"] = VOX_ACCOUNT_NAME
    else:
        raise RuntimeError("Set VOXIMPLANT_ACCOUNT_ID or VOXIMPLANT_ACCOUNT_NAME")
    phone_e164 = to_e164_ru(phone)
    # Важно: script_custom_data — строка. Туда кладем JSON.
    custom = {
        "session_id": call_session_id,
        "phone": phone_e164,
        "knowledge_base": knowledge_base,
        "backend_url": PUBLIC_BACKEND_URL.rstrip("/"),
        "backend_token": os.getenv("BACKEND_TOKEN", ""),  # Пустая строка если None
        "caller_id": DEFAULT_CALLER_ID,
        "tts_voice": "Yandex.alena",
        "language": "ru-RU",
    }
    payload = {
        "rule_id": rule_id,
        "script_custom_data": json.dumps(custom, ensure_ascii=False),
    }

    url = f"{VOX_API_BASE}/StartScenarios"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params, data=payload, timeout=30) as resp:
            text = await resp.text()
            try:
                data = json.loads(text)
            except Exception:
                raise RuntimeError(f"Voximplant returned non-JSON: {text[:300]}")

            if "error" in data:
                raise RuntimeError(f"Voximplant error: {data['error']}")

            return data


async def run_voximplant_campaign(call_session_id: int, phones: List[str], knowledge_base: str) -> None:
    """
    Запускает обзвон: на каждый телефон — отдельный StartScenarios (отдельная VoxEngine-сессия).
    Итоги разговора должен прислать JS-сценарий в твой FastAPI.
    """
    logger.info("[VOX] campaign started. session_id=%s, phones=%d", call_session_id, len(phones))

    for phone in phones:
        try:
            result = await _start_scenario(phone=phone, call_session_id=call_session_id, knowledge_base=knowledge_base)
            # Часто возвращается call_session_history_id — можно сохранить себе для дебага
            csh = result.get("call_session_history_id")
            logger.info("[VOX] StartScenarios OK. phone=%s, call_session_history_id=%s", phone, csh)
        except Exception as e:
            logger.exception("[VOX] StartScenarios FAILED. phone=%s err=%s", phone, e)


        await asyncio.sleep(0.7)

    logger.info("[VOX] campaign finished. session_id=%s", call_session_id)
