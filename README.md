# Мессенджер (Messenger MVP)

Серверная часть мессенджера для быстрого обмена сообщениями в реальном времени. 
Проект реализует базовый MVP с поддержкой личных и групповых чатов, авторизацией, 
поиском по сообщениям и доставкой сообщений в реальном времени.

##  Стек технологий

- **Язык:** Python 3.11+
- **Web-фреймворк:** FastAPI (async)
- **База данных:** PostgreSQL 15
- **ORM:** SQLAlchemy 2.0 (асинхронный режим)
- **Брокер сообщений:** Apache Kafka (клиент `aiokafka`)
- **Real-time:** WebSockets
- **Авторизация:** JWT (PyJWT), хэширование паролей (bcrypt/passlib)
- **Нагрузочное тестирование:** Locust
- **Инфраструктура:** Docker, Docker Compose

## 🏗 Архитектура

Приложение построено по классической трехуровневой архитектуре:
1. **API Layer (FastAPI):** Принимает HTTP и WebSocket запросы.
2. **Service/Business Layer:** Обрабатывает бизнес-логику, валидацию и права доступа.
3. **Data Layer:** Взаимодействует с PostgreSQL (хранение данных) и Kafka (событийная шина для real-time доставки).

**Поток сообщения в реальном времени:**
`Клиент A (REST API)`  `FastAPI` ➔ `PostgreSQL (сохранение)` + `Kafka (публикация события)` ➔ `Kafka Consumer` ➔ `WebSocket Manager` ➔ `Клиент B (WebSocket)`

##  Структура проекта

```text
messenger/
├── app/
│   ├── __init__.py
│   ├── main.py              # Точка входа, инициализация FastAPI, роутеры
│   ├── config.py            # Настройки приложения (pydantic-settings)
│   ├── db.py                # Настройка SQLAlchemy engine, сессии, create_all
│   ├── logging_config.py    # Конфигурация структурированного логирования
│   ├── auth/                # Модуль авторизации
│   │   ├── router.py        # Эндпоинты /register, /login
│   │   ├── dependencies.py  # Dependency get_current_user
│   │   └── utils.py         # Утилиты JWT и хэширования паролей
│   ├── chats/               # Модуль управления чатами
│   │   ├── router.py        # Эндпоинты CRUD чатов и участников
│   │   └── schemas.py       # Pydantic схемы для чатов
│   ├── messages/            # Модуль сообщений
│   │   ├── router.py        # Эндпоинты отправки, истории и поиска
│   │   └── schemas.py       # Pydantic схемы для сообщений
│   ├── models/              # SQLAlchemy модели данных
│   │   ├── user.py
│   │   ├── chat.py
│   │   └── message.py
│   ├── kafka/               # Интеграция с Apache Kafka
│   │   ├── producer.py      # Публикация событий (сообщения, участники)
│   │   └── consumer.py      # Фоновое потребление событий
│   └── websocket/           # WebSocket инфраструктура
│       ├── router.py        # WebSocket эндпоинт /ws
│       └── manager.py       # Connection Manager (управление подключениями)
├── scripts/
│   └── create_tables.py     # Скрипт инициализации схемы БД (create_all)
── load_tests/
│   └── locustfile.py        # Сценарии нагрузочного тестирования (Locust)
├── tests/                   # Функциональные и интеграционные тесты
├── docker-compose.yml       # Оркестрация PostgreSQL и Kafka
├── .env.example             # Шаблон переменных окружения
├── requirements.txt         # Зависимости Python
└── README.md                # Документация проекта