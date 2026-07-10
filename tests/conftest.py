"""Общие фикстуры тестов API.

Изоляция от прод-БД: каждый тест получает свежую in-memory SQLite (StaticPool —
одно общее соединение, чтобы схема и данные были видны между запросами) и через
`app.dependency_overrides[get_db]` подменяет сессию. Схема создаётся из моделей
(`Base.metadata.create_all`), а не миграцией — уникальность email в модели (unique=True)
покрывает те же кейсы. lifespan (index-поллер) при ASGITransport не стартует, реальная
БД не трогается.
"""

from __future__ import annotations

import os

# ВАЖНО: выставить обязательные переменные ДО импорта app.* — Settings() читает их на импорте.
# URL «постгресовый» специально: app.db.session на импорте создаёт async-engine с
# pool_size/max_overflow (для SQLite это невалидно). Реального коннекта нет — движок
# ленив, а get_db в тестах подменяется на in-memory SQLite ниже.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/testdb"
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-32")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "10")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("S3_ACCESS_KEY", "test-access")
os.environ.setdefault("S3_SECRET_KEY", "test-secret")
os.environ.setdefault("CLOUD_FUNCTION_API_KEY", "test-cf-key")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.db.models as _models  # noqa: E402, F401  регистрирует таблицы в Base.metadata
from app.db import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def sessionmaker() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient, None]:
    # Повторяем контракт прод-get_db: commit при успехе, rollback при ошибке.
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
