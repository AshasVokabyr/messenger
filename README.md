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
> /register alice secret123    # регистрация
> /register bob secret123
> /login alice                  # войти как alice
> /personal bob                 # создать личный чат с bob
> /enter bob                    # войти в чат + показать историю
> Привет, Боб!                  # отправить сообщение
> /back                         # выйти из чата в меню
> /chats                        # список чатов
> /group group1 bob alice       # создать групповой чат
> /enter group1                 # войти в групповой чат
> /leave group1                 # отписаться от чата
> /help                         # все команды
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
│   ├── messages/            # Модуль сообщений
│   │   ├── router.py        # Эндпоинты отправки, истории и поиска
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
| POST | `/chats/{chat_id}/messages` | Отправить сообщение |
| GET | `/chats/{chat_id}/messages` | История сообщений (пагинация) |
| GET | `/chats/{chat_id}/messages/search?q=` | Поиск по сообщениям в чате |
| GET | `/messages/search?q=` | Глобальный поиск по сообщениям |
| WS | `/ws?token=` | WebSocket для real-time |
| GET | `/health` | Health check |

## Тестирование

```bash
pytest
```

Все тесты используют SQLite (test.db) для изоляции. Kafka мокируется через `AsyncMock`.

## Команды CLI-клиента

| Команда | Описание |
|---------|----------|
| `/register <l> <p>` | Регистрация и вход |
| `/login <l> <p>` | Вход в существующий аккаунт |
| `/logout` | Выход из аккаунта |
| `/chats` | Список чатов |
| `/join <ref>` | Подписаться на чат |
| `/leave <ref>` | Отписаться от чата |
| `/enter <ref> [N]` | Войти в чат + показать N сообщений |
| `/switch [ref]` | Переключиться между чатами |
| `/back` | Выйти из чата в меню |
| `/personal <login>` | Создать личный чат по логину |
| `/group <name> <logins>` | Создать групповой чат |
| `/users <query>` | Поиск пользователей |
| `/messages [N]` | Показать последние N сообщений |
| `/members` | Участники текущего чата |
| `/clear` | Очистить экран |
| `/help` | Справка |
| `/quit` / `/exit` | Выход |

`<ref>` может быть: номер из `/chats`, логин (для личных чатов), имя группового чата, или UUID.
