# API

Бэкенд Petergof Science RAG: FastAPI, PostgreSQL, аутентификация по JWT.

## Локальный запуск

### Требования

- Python 3.13+
- [Poetry](https://python-poetry.org/)
- Docker и Docker Compose (для PostgreSQL)

### Шаги

1. **Поднять PostgreSQL**

   ```bash
   docker compose up -d db
   ```

   БД будет доступна на `localhost:5432`. Учётные данные из `docker-compose.yml`: пользователь `andrey`, пароль `Password`, база `rag_database`.

2. **Установить зависимости**

   ```bash
   poetry install
   ```

3. **Настроить окружение**

   Скопировать пример переменных и заполнить значения:

   ```bash
   cp .env.example .env
   ```

   В `app/core/config.py` используются переменные:
   - `DATABASE_URL` — строка подключения к PostgreSQL (для asyncpg: `postgresql+asyncpg://user:password@localhost:5432/rag_database`);
   - `JWT_SECRET_KEY` — секрет для подписи JWT;
   - `JWT_ALGORITHM` — алгоритм (по умолчанию `HS256`);
   - `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` — срок жизни токенов.

4. **Применить миграции**

   ```bash
   poetry run alembic upgrade head
   ```

5. **Запустить сервер**

   ```bash
   poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   API будет доступно по адресу: http://localhost:8000
   Документация: http://localhost:8000/docs
