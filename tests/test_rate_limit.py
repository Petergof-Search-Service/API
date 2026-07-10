"""Тесты rate limiting (API-03): 429 на /token, /register, /answer.

Лимитер по умолчанию выключен autouse-фикстурой `reset_limiter` (conftest), чтобы
не мешать прочим тестам. Каждый тест здесь включает его явно и чистит storage.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.rate_limit import limiter
from app.core.security import create_token, hash_password
from app.db.models import (
    INDEX_READY,
    Chat,
    Organization,
    OrgIndex,
    User,
    UserOrganization,
)
from app.db.models.user_settings import UserSetting


async def test_token_rate_limited(client: AsyncClient) -> None:
    limiter.reset()
    limiter.enabled = True

    # RATE_LIMIT_LOGIN=5/minute: первые 5 в пределах лимита (401 — юзера нет,
    # это не важно), 6-й запрос за минуту → 429.
    for i in range(5):
        resp = await client.post(
            "/api/v1/token", data={"username": "nobody@x.ru", "password": "x"}
        )
        assert resp.status_code != 429, f"request {i} unexpectedly rate-limited"

    sixth = await client.post(
        "/api/v1/token", data={"username": "nobody@x.ru", "password": "x"}
    )
    assert sixth.status_code == 429


async def test_register_rate_limited(client: AsyncClient) -> None:
    limiter.reset()
    limiter.enabled = True

    # Разные email, чтобы упереться именно в лимит, а не в 409-дубликат.
    statuses = [
        (
            await client.post(
                "/api/v1/register",
                json={"email": f"user{i}@x.ru", "password": "pw123456"},
            )
        ).status_code
        for i in range(6)
    ]

    assert 429 not in statuses[:5], statuses
    assert statuses[5] == 429, statuses


async def _seed_answer_graph(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[str, int, int, int]:
    """Минимальный граф для happy-path /answer.

    Возвращает (access_token, org_id, index_id, chat_id). Вставляем напрямую в БД,
    а токен минтим `create_token`, чтобы не расходовать лимиты auth-эндпоинтов.
    """
    email = "asker@x.ru"
    async with sessionmaker() as session:
        user = User(
            email=email,
            hashed_password=hash_password("pw123456"),
            settings=UserSetting(),
        )
        session.add(user)
        await session.flush()

        org = Organization(name="Org")
        session.add(org)
        await session.flush()

        session.add(UserOrganization(user_id=user.id, org_id=org.id, role="user"))
        index = OrgIndex(
            org_id=org.id,
            name="idx",
            vector_store_id="vs_test",
            status=INDEX_READY,
        )
        session.add(index)
        chat = Chat(user_id=user.id, title="chat")
        session.add(chat)
        await session.commit()

        token = create_token({"sub": email, "type": "access"})
        return token, org.id, index.id, chat.id


async def test_answer_rate_limited_does_not_call_llm(
    client: AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    async def fake_get_answer(**kwargs: object) -> tuple[str, str]:
        calls["n"] += 1
        return "mock answer", "mock context"

    # Патчим имя в неймспейсе эндпоинта (там `from rag.main import get_answer`).
    monkeypatch.setattr("app.api.v1.endpoints.rag.get_answer", fake_get_answer)

    token, org_id, index_id, chat_id = await _seed_answer_graph(sessionmaker)

    limiter.reset()
    limiter.enabled = True

    headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org_id)}
    body = {
        "index_id": index_id,
        "question": "Кто построил Петергоф?",
        "chat_id": chat_id,
    }

    # RATE_LIMIT_ANSWER=20/minute per identity (ключ user_or_ip_key по sub токена):
    # 20 запросов проходят и зовут (мок) LLM, 21-й → 429.
    for i in range(20):
        resp = await client.post("/api/v1/answer", json=body, headers=headers)
        assert resp.status_code == 200, (i, resp.status_code, resp.text)

    assert calls["n"] == 20

    blocked = await client.post("/api/v1/answer", json=body, headers=headers)
    assert blocked.status_code == 429
    # Ключевой AC: при 429 LLM НЕ вызывается — лимит срабатывает до тела хендлера.
    assert calls["n"] == 20
