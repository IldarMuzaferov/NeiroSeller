import requests
import json
from datetime import datetime

# Твои данные
LOGIN = "Sika16@mail.ru"  # Твой логин
PASSWORD = "P1xgpmqm"  # Тот, который ввел


def get_api_token():
    """Получаем токен для работы с Call API"""

    payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "login.user",
        "params": {
            "login": LOGIN,
            "password": PASSWORD
        }
    }

    try:
        response = requests.post(
            "https://callapi.uiscom.ru/v4.0",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        data = response.json()

        if "result" in data and "data" in data["result"]:
            token = data["result"]["data"]["access_token"]
            expire_timestamp = data["result"]["data"]["expire_at"]

            # Конвертируем timestamp в читаемую дату
            expire_date = datetime.fromtimestamp(expire_timestamp)

            print("=" * 60)
            print("✅ API РАБОТАЕТ! Токен получен успешно!")
            print("=" * 60)
            print(f"\n🔑 Access Token: {token}")
            print(f"⏰ Действует до: {expire_date}")

            # Показываем лимиты
            limits = data["result"]["metadata"]["limits"]
            print(f"\n📊 Лимиты API:")
            print(f"• Дневной: {limits['day_limit']} баллов")
            print(f"• Осталось сегодня: {limits['day_remaining']} баллов")
            print(f"• Минутный: {limits['minute_limit']} баллов")
            print(f"• Осталось в минуту: {limits['minute_remaining']} баллов")

            return token
        else:
            print("❌ Неожиданный формат ответа")
            print("Ответ API:", json.dumps(data, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"⚠️ Ошибка: {e}")

    return None


# Запускаем
token = get_api_token()

if token:
    print("\n" + "=" * 60)
    print("🎉 ВСЁ ГОТОВО ДЛЯ РАБОТЫ С API!")
    print("=" * 60)
    print("\n📝 Используй этот токен в следующих запросах:")
    print(f"access_token = '{token}'")

    # Пример следующего шага
    print("\n🚀 Теперь можно сделать тестовый звонок:")
    print("""# Пример запроса для звонка
payload = {
    "id": 2,
    "jsonrpc": "2.0",
    "method": "start.simple_call",
    "params": {
        "access_token": "%s",
        "from_number": "ТВОЙ_НОМЕР_UISCOM",
        "to_number": "НОМЕР_КЛИЕНТА",
        "tts_message": "Привет! Это тестовый звонок от ИИ-агента."
    }
}""" % token)
