"""Тесты регистрации/логина под API-02: UNIQUE(email) + атомарная регистрация → 409,
нормализация email к нижнему регистру.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.user import User


async def _user_count(
    sessionmaker: async_sessionmaker[AsyncSession], email: str
) -> int:
    async with sessionmaker() as session:
        result: int | None = await session.scalar(
            select(func.count()).select_from(User).where(User.email == email)
        )
        return result or 0


async def test_register_returns_token(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/register", json={"email": "new@x.ru", "password": "pw123456"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_register_duplicate_returns_409(
    client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    first = await client.post(
        "/api/v1/register", json={"email": "dup@x.ru", "password": "pw123456"}
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/v1/register", json={"email": "dup@x.ru", "password": "other123"}
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "User already registered"

    # Второй строки не появилось.
    assert await _user_count(sessionmaker, "dup@x.ru") == 1


async def test_register_email_case_insensitive_conflict(
    client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    first = await client.post(
        "/api/v1/register", json={"email": "foo@x.ru", "password": "pw123456"}
    )
    assert first.status_code == 200

    # Тот же email в другом регистре и с пробелами → тот же аккаунт → 409.
    second = await client.post(
        "/api/v1/register", json={"email": "  FOO@X.RU  ", "password": "pw123456"}
    )
    assert second.status_code == 409

    assert await _user_count(sessionmaker, "foo@x.ru") == 1


async def test_login_normalizes_email(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/register", json={"email": "login@x.ru", "password": "pw123456"}
    )

    # Логин тем же email в верхнем регистре и с пробелами — успешно.
    resp = await client.post(
        "/api/v1/token",
        data={"username": "  LOGIN@X.RU  ", "password": "pw123456"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_after_would_be_duplicate_email_no_500(
    client: AsyncClient,
) -> None:
    await client.post(
        "/api/v1/register", json={"email": "safe@x.ru", "password": "pw123456"}
    )
    dup = await client.post(
        "/api/v1/register", json={"email": "safe@x.ru", "password": "pw123456"}
    )
    assert dup.status_code == 409

    # Ранее дубликат сломал бы get_user (MultipleResultsFound → 500). Теперь логин
    # либо 200 (верный пароль), либо 401 (неверный) — но НЕ 500.
    resp = await client.post(
        "/api/v1/token",
        data={"username": "safe@x.ru", "password": "pw123456"},
    )
    assert resp.status_code == 200
