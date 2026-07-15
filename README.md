# Мессенджер (Messenger MVP)

Серверная часть мессенджера для быстрого обмена сообщениями в реальном времени.
Проект реализует базовый MVP с поддержкой личных и групповых чатов, авторизацией,
поиском по сообщениям и доставкой сообщений в реальном времени.

## Стек технологий

- **Язык:** Python 3.11+
- **Web-фреймворк:** FastAPI (async)
- **База данных:** PostgreSQL 15
- **ORM:** SQLAlchemy 2.0 (асинхронный режим)
- **Брокер сообщений:** Apache Kafka (клиент `aiokafka`)
- **Real-time:** WebSockets
- **Авторизация:** JWT (PyJWT), хэширование паролей (bcrypt)
- **CLI-клиент:** prompt_toolkit, httpx, websockets
- **Инфраструктура:** Docker, Docker Compose

## Архитектура

Приложение построено по классической трехуровневой архитектуре:
1. **API Layer (FastAPI):** Принимает HTTP и WebSocket запросы.
2. **Service/Business Layer:** Обрабатывает бизнес-логику, валидацию и права доступа.
3. **Data Layer:** Взаимодействует с PostgreSQL (хранение данных) и Kafka (событийная шина для real-time доставки).

**Поток сообщения в реальном времени:**
`Клиент A (REST)` → `FastAPI` → `PostgreSQL (сохранение)` + `Kafka (публикация)` → `Kafka Consumer` → `WebSocket Manager` → `Клиент B (WS)`

**Надёжность Kafka:**
- **Producer:** retry 1/2/4 секунды при ошибке отправки, после 3 неудач — CRITICAL лог (не блокирует ответ клиенту)
- **Consumer:** exponential backoff при потере связи (1→30s, max 10 retries)

## Быстрый старт

### 1. Запуск инфраструктуры

```bash
docker compose up -d
```

Поднимет PostgreSQL и Kafka.

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
# или через pyproject.toml:
pip install -e .
```

### 3. Запуск сервера

```bash
uvicorn app.main:app --reload
```

Таблицы БД создадутся автоматически при старте (через `Base.metadata.create_all`).

Проверить: `http://localhost:8000/health` → `{"status": "ok"}`

### 4. Работа через CLI-клиент

```bash
python client.py interactive
```

Внутри interactive-режима:

```
> /register alice secret123       # регистрация
> /personal bob                   # создать личный чат с bob
> /enter bob                      # войти в чат + показать историю
> Привет, Боб!                    # отправить сообщение
> /back                           # выйти из чата в меню
> /chats                          # список чатов
> /group group1 bob eve           # создать групповой чат
> /enter group1                   # войти в групповой чат
> /invite group1 eve              # добавить участника
> /messages 10                    # показать последние 10 сообщений
> /search привет                  # глобальный поиск
> /leave group1                   # покинуть групповой чат
> /del_chat group1                # удалить чат (только админ)
> /members                        # список участников с ролями
> /role group1 eve moderator      # назначить модератора (админ)
> /del_message 3                  # удалить сообщение №3
> /help                           # все команды
```

### 5. Работа через curl

**Регистрация:**
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"login": "alice", "password": "secret123"}'
```

**Логин:**
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"login": "alice", "password": "secret123"}'
```

**Список чатов:**
```bash
TOKEN="<jwt_from_login>"
curl http://localhost:8000/chats/ \
  -H "Authorization: Bearer $TOKEN"
```

**Создать личный чат:**
```bash
curl -X POST "http://localhost:8000/chats/personal/<user_id>" \
  -H "Authorization: Bearer $TOKEN"
```

**Создать групповой чат:**
```bash
curl -X POST http://localhost:8000/chats/group \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "group1", "participant_ids": ["<user_id_bob>", "<user_id_alice>"]}'
```

**Отправить сообщение:**
```bash
curl -X POST "http://localhost:8000/chats/<chat_id>/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello!"}'
```

**История сообщений (пагинация):**
```bash
curl "http://localhost:8000/chats/<chat_id>/messages?limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

**Поиск по сообщениям в чате:**
```bash
curl "http://localhost:8000/chats/<chat_id>/messages/search?q=hello" \
  -H "Authorization: Bearer $TOKEN"
```

**Подключение к WebSocket (через wscat):**
```bash
# установите wscat: npm install -g wscat
TOKEN="<jwt>"
wscat -c "ws://localhost:8000/ws?token=$TOKEN"
# после подключения:
# > {"action": "join", "chat_id": "<chat_id>"}
# < {"type": "joined", "chat_id": "..."}
```

## Структура проекта

```text
messenger/
├── app/
│   ├── main.py              # Точка входа, инициализация FastAPI, роутеры
│   ├── config.py            # Настройки приложения (pydantic-settings)
│   ├── db.py                # Настройка SQLAlchemy engine, сессии
│   ├── logging_config.py    # Конфигурация структурированного логирования
│   ├── middleware.py        # RequestContextMiddleware
│   ├── exceptions_handlers.py # Глобальные обработчики ошибок
│   ├── auth/                # Модуль авторизации
│   │   ├── router.py        # Эндпоинты /register, /login
│   │   ├── schemas.py       # Pydantic схемы
│   │   ├── dependencies.py  # Dependency get_current_user
│   │   └── utils.py         # Утилиты JWT и хэширования паролей
│   ├── chats/               # Модуль управления чатами
│   │   ├── router.py        # Эндпоинты CRUD чатов и участников
│   │   └── schemas.py       # Pydantic схемы для чатов
│   ├── messages/            # Глобальный поиск сообщений
│   │   ├── router.py        # Эндпоинт /messages/search
│   │   └── schemas.py       # Pydantic схемы для сообщений
│   ├── users/               # Модуль поиска пользователей
│   │   ├── router.py        # Эндпоинты /users/by-login, /users/search
│   │   └── schemas.py       # Pydantic схемы
│   ├── models/              # SQLAlchemy модели данных
│   │   ├── user.py
│   │   ├── chat.py
│   │   ├── chat_participant.py
│   │   └── message.py
│   ├── kafka/               # Интеграция с Apache Kafka
│   │   ├── producer.py      # Публикация событий
│   │   ├── consumer.py      # Фоновое потребление событий
│   │   └── handlers.py      # Обработчики событий
│   └── websocket/           # WebSocket инфраструктура
│       ├── router.py        # WebSocket эндпоинт /ws
│       ├── auth.py          # Аутентификация через query-параметр
│       └── manager.py       # Connection Manager
├── load_tests/
│   └── locustfile.py        # Сценарии нагрузочного тестирования (Locust)
├── tests/                   # Функциональные и интеграционные тесты
├── client.py                # CLI-клиент
├── docker-compose.yml       # Оркестрация PostgreSQL и Kafka
├── .env.example             # Шаблон переменных окружения
├── requirements.txt         # Зависимости Python
└── README.md                # Документация проекта
```

## API Эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/auth/register` | Регистрация пользователя |
| POST | `/auth/login` | Логин, получение JWT |
| GET | `/users/by-login/{login}` | Поиск пользователя по логину |
| GET | `/users/search?q=` | Поиск пользователей по части логина |
| GET | `/chats/` | Список чатов пользователя |
| GET | `/chats/{chat_id}` | Информация о чате |
| POST | `/chats/personal/{user_id}` | Создать/получить личный чат |
| POST | `/chats/group` | Создать групповой чат |
| POST | `/chats/{chat_id}/participants` | Добавить участников (админ) |
| DELETE | `/chats/{chat_id}/participants/{user_id}` | Удалить участника (админ) |
| PATCH | `/chats/{chat_id}/participants/{user_id}/role` | Сменить роль участника (админ) |
| POST | `/chats/{chat_id}/leave` | Выйти из чата |
| DELETE | `/chats/{chat_id}` | Удалить чат (админ) |
| POST | `/chats/{chat_id}/messages` | Отправить сообщение |
| GET | `/chats/{chat_id}/messages` | История сообщений (пагинация) |
| GET | `/chats/{chat_id}/messages/search?q=` | Поиск по сообщениям в чате |
| DELETE | `/chats/{chat_id}/messages/{message_id}` | Удалить сообщение |
| GET | `/messages/search?q=` | Глобальный поиск по сообщениям |
| WS | `/ws?token=` | WebSocket для real-time |
| GET | `/health` | Health check |

## Переменные окружения

Копия `.env.example` → `.env`:

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Подключение к PostgreSQL |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Адрес Kafka (KRaft) |
| `JWT_SECRET_KEY` | `secret` | Ключ подписи JWT |
| `JWT_ALGORITHM` | `HS256` | Алгоритм JWT |
| `JWT_EXPIRATION_MINUTES` | `60` | Время жизни токена |
| `BCRYPT_ROUNDS` | `12` | Итерации хэширования паролей |

## Тестирование

```bash
pytest
```

Все тесты используют SQLite (test.db) для изоляции. Kafka мокируется через `AsyncMock`.

## Команды CLI-клиента

```
── Authentication ──────────────────────────
  /register <l> <p>        Register a new user
  /login <l> <p>           Log in as existing user
  /logout                  Log out and return to anonymous mode
  /exit                    Exit the program

── Chat Management ─────────────────────────
  /personal <login>        Create personal chat by login
  /group <name> <l1>...    Create group chat
  /invite <ref> <login>    Add participant to chat
  /kick <ref> <login>      Remove participant (admin only)
  /leave <ref>             Leave chat (remove yourself from participants)
  /del_chat <ref>          Delete chat (admin only)
  /role <ref> <l> <r>      Set role (moderator|member) of participant (admin only)

── Navigation ──────────────────────────────
  /chats                   List your chats (numbered)
  /enter <ref> [N]         Enter chat + show last N messages
  /switch [ref]            Switch current chat (list if no ref)
  /back                    Go to main menu (keep subscriptions)

── Messages ────────────────────────────────
  /messages [N]            Show last N messages in current chat
  /search <query>          Search messages across all your chats
  /del_message <N>         Delete message N from last /messages output
  <any text>               Send message to current chat

── Info ────────────────────────────────────
  /help                    Show this help
  /users <query>           Search users by login
  /members                 Show members of current chat (with roles)
  /clear                   Clear terminal screen
```

`<ref>` может быть: номер из `/chats`, логин (для личных чатов), имя чата или UUID.

## Роли и права доступа

Система ролей на уровне участников группового чата:

| Роль | Права |
|---|---|
| `member` | Чтение и отправка сообщений, удаление своих сообщений |
| `moderator` | Всё что `member` + удаление любых сообщений в чате |
| `admin` | Всё что `moderator` + управление участниками (добавление, удаление, смена ролей), удаление чата |

В личных чатах все участники имеют роль `member`, управление участниками недоступно.

Просмотр ролей: `/members` в чате.
Назначение модератора: `/role <ref> <login> moderator` (только админ).
