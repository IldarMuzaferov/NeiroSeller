# CallSeller

<p align="center">
  <b>Telegram-бот для запуска AI-обзвонов, сбора результатов и анализа интереса клиентов.</b>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="Aiogram" src="https://img.shields.io/badge/aiogram-3.x-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-API-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-Async-4169E1?style=for-the-badge&logo=postgresql&logoColor=white">
</p>

---

## О проекте

**CallSeller** помогает запускать исходящие звонки по списку номеров прямо из Telegram. Пользователь вводит телефоны, добавляет базу знаний о компании или продукте, подтверждает запуск, а система инициирует звонки через Voximplant, ведет диалог с клиентом через AI-ассистента и сохраняет результаты в базу данных.

Проект состоит из Telegram-бота на **aiogram**, асинхронной БД через **SQLAlchemy**, HTTP/WebSocket API на **FastAPI** и интеграции с **Voximplant** для телефонии.

## Возможности

- Запуск нового обзвона из Telegram.
- Ввод списка номеров в разных форматах.
- Передача базы знаний для персонализации разговора.
- Создание и хранение сессий обзвона.
- Автоматический запуск исходящих звонков через Voximplant.
- WebSocket-обмен с голосовым ассистентом.
- Генерация ответов и анализ разговора через OpenAI-compatible API.
- Сохранение результата каждого звонка: статус, детали интереса, заметки, длительность.
- Просмотр статистики по завершенным сессиям.
- Удаление отдельных или всех завершенных сессий.

## Как это работает

```mermaid
flowchart LR
    A[Telegram Admin] --> B[aiogram bot]
    B --> C[(Database)]
    B --> D[FastAPI /call]
    D --> E[Voximplant StartScenarios]
    E --> F[Phone Call]
    E <--> G[FastAPI WebSocket /ws]
    G --> H[AI Assistant]
    G --> C
    G --> B
```

1. Администратор открывает бота и выбирает запуск нового обзвона.
2. Бот просит список телефонов и информацию о компании.
3. Данные сохраняются в таблицу `call_sessions`.
4. После подтверждения бот вызывает backend endpoint для старта звонков.
5. Voximplant запускает сценарий звонка и подключается к WebSocket API.
6. AI-ассистент ведет диалог, анализирует результат и сохраняет его в `call_results`.
7. Пользователь получает результаты в Telegram и может посмотреть статистику по сессиям.

## Стек

| Слой | Технологии |
| --- | --- |
| Telegram bot | aiogram 3 |
| API | FastAPI, Uvicorn |
| Database | PostgreSQL, SQLAlchemy async, asyncpg |
| AI | OpenAI-compatible Chat Completions API |
| Telephony | Voximplant Platform API |
| Config | python-dotenv |

## Структура проекта

```text
CallSeller/
├── api_router.py              # FastAPI router для сохранения результатов звонков
├── create_bot.py              # Инициализация Bot и Dispatcher
├── main.py                    # Точка входа Telegram-бота
├── requirements.txt           # Python-зависимости
├── database/
│   ├── engine.py              # Async SQLAlchemy engine/session
│   ├── models.py              # Модели User, CallSession, CallResult
│   └── orm_query.py           # CRUD-операции и утилиты
├── filters/
│   └── chat_types.py          # Фильтры чатов и админ-доступа
├── handlers/
│   ├── admin_private.py       # Основная логика Telegram-обзвона
│   ├── user_group.py          # Обработчики групп
│   └── user_private.py        # Приватные пользовательские обработчики
├── kbds/
│   └── inline.py              # Inline-клавиатуры
├── middlewares/
│   └── db.py                  # Middleware для DB session
└── services/
    ├── voximplant_api.py      # FastAPI-приложение голосового ассистента
    └── voximplant_client.py   # Клиент Voximplant Platform API
```

## Быстрый старт

### 1. Клонировать репозиторий

```bash
git clone https://github.com/<your-username>/CallSeller.git
cd CallSeller
```

### 2. Создать виртуальное окружение

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

Linux/macOS:

```bash
source venv/bin/activate
```

### 3. Установить зависимости

```bash
pip install -r requirements.txt
```

### 4. Настроить переменные окружения

Создайте файл `.env` в корне проекта:

```env
# Telegram
TOKEN=your_telegram_bot_token

# Database
DB_URL=postgresql+asyncpg://user:password@localhost:5432/callseller

# Voximplant
VOXIMPLANT_API_KEY=your_voximplant_api_key
VOXIMPLANT_ACCOUNT_ID=your_account_id
# или вместо VOXIMPLANT_ACCOUNT_ID:
# VOXIMPLANT_ACCOUNT_NAME=your_account_name
VOXIMPLANT_RULE_ID=your_rule_id
VOXIMPLANT_CALLER_ID=your_caller_id

# Public backend URL for Voximplant callbacks/WebSocket
PUBLIC_BACKEND_URL=https://your-domain.com

# Optional internal backend token
BACKEND_TOKEN=change_me
```

> Важно: не коммитьте `.env`, реальные токены, API-ключи и приватные URL в GitHub.

### 5. Подготовить PostgreSQL

Создайте базу данных и укажите DSN в `DB_URL`. Таблицы создаются автоматически при старте бота через `create_db()`.

Пример локального DSN:

```env
DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/callseller
```

## Запуск

### Telegram-бот

```bash
python main.py
```

После запуска бот:

- инициализирует таблицы БД;
- подключает middleware для DB session;
- регистрирует admin/user роутеры;
- начинает polling Telegram updates.

### Голосовой backend / Voximplant API

```bash
uvicorn services.voximplant_api:app --host 0.0.0.0 --port 1111
```

Основные endpoints:

| Method | Endpoint | Назначение |
| --- | --- | --- |
| `POST` | `/call` | Инициировать исходящий звонок |
| `WS` | `/ws` | WebSocket для Voximplant-сценария |
| `POST` | `/speech` | HTTP fallback для генерации ответа |
| `POST` | `/end_call` | Завершить сессию |
| `POST` | `/save_result` | Зафиксировать результат звонка |
| `GET` | `/health` | Проверка состояния |
| `GET` | `/sessions` | Активные голосовые сессии |

## Использование в Telegram

1. Напишите боту `/start`.
2. Нажмите **Новый обзвон**.
3. Отправьте номера телефонов через пробел или с новой строки.
4. Отправьте информацию о компании, продуктах, услугах и важных деталях.
5. Проверьте данные и подтвердите запуск.
6. Дождитесь результатов звонков в чате.

Поддерживаемые форматы телефонов:

```text
+79161234567
8 (916) 123-45-67
79161234567
9161234567
```

## Модель данных

```mermaid
erDiagram
    users ||--o{ call_sessions : owns
    call_sessions ||--o{ call_results : contains

    users {
        bigint id PK
        string username
        string first_name
        string last_name
        boolean is_admin
        datetime created
        datetime updated
    }

    call_sessions {
        int id PK
        bigint user_id FK
        string name
        text phone_numbers
        text knowledge_base
        string status
        datetime started_at
        datetime completed_at
        datetime created
        datetime updated
    }

    call_results {
        int id PK
        int session_id FK
        string phone_number
        string status
        text interest_details
        text notes
        int call_duration
        datetime created
        datetime updated
    }
```

## Статусы

### Статусы сессий

| Статус | Значение |
| --- | --- |
| `draft` | Сессия создана, но обзвон еще не запущен |
| `active` | Обзвон выполняется |
| `completed` | Все номера обработаны |
| `cancelled` | Сессия отменена |

### Статусы звонков

| Статус | Значение |
| --- | --- |
| `interested` | Клиент заинтересован |
| `not_interested` | Клиент отказался |
| `callback_requested` | Клиент попросил перезвонить |
| `no_answer` | Нет ответа |
| `busy` | Линия занята |
| `error` | Ошибка обработки |

## Настройка Voximplant

Для полноценной работы нужно:

1. Создать аккаунт Voximplant.
2. Настроить приложение и правило звонка.
3. Получить `VOXIMPLANT_API_KEY`, `VOXIMPLANT_ACCOUNT_ID` или `VOXIMPLANT_ACCOUNT_NAME`, `VOXIMPLANT_RULE_ID`.
4. Сделать backend публично доступным по HTTPS.
5. Указать публичный адрес в `PUBLIC_BACKEND_URL`.
6. В VoxEngine-сценарии передавать события звонка в WebSocket endpoint `/ws`.

## Безопасность

Перед публикацией репозитория проверьте:

- `.env` добавлен в `.gitignore`;
- в коде нет реальных API-ключей, токенов и account id;
- все секреты читаются из переменных окружения;
- публичные endpoints защищены токеном или сетевыми правилами;
- доступ к боту ограничен нужными администраторами.

## Полезные команды

```bash
# Запуск Telegram-бота
python main.py

# Запуск голосового API
uvicorn services.voximplant_api:app --host 0.0.0.0 --port 1111

# Проверка health endpoint
curl http://localhost:1111/health
```

## Roadmap

- [ ] Вынести все hardcoded credentials в `.env`.
- [ ] Добавить Alembic-миграции.
- [ ] Добавить роли и список администраторов.
- [ ] Добавить retry-логику для неуспешных звонков.
- [ ] Добавить экспорт результатов в CSV/XLSX.
- [ ] Покрыть CRUD и обработчики тестами.

## Лицензия

Лицензия не указана. Если проект планируется публиковать, добавьте файл `LICENSE`.

