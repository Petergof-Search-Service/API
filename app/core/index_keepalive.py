"""Keep-alive поисковых индексов (vector store в AI Studio).

Стор создаётся с TTL ``expires_after={"anchor": "last_active_at", "days": 30}``
(см. ``rag/create_index.py``): если по индексу 30 дней не искали, AI Studio удаляет
стор, а durable-строка в БД остаётся ``ready`` — и чат молча получает 404 на поиске.

Эта петля раз в ``INDEX_KEEPALIVE_INTERVAL_SECONDS`` проходит по всем ``ready``-индексам
и делает дешёвый ``vector_stores.search`` (``touch_index``) — это «использование», оно
сбрасывает ``last_active_at`` и продлевает TTL. Побочно чиним рассинхрон: если стор уже
пропал (``NotFoundError`` / 404), помечаем строку ``failed``, чтобы UI/чат не считали
индекс живым.

Петля поднимается в ``app/main.py`` (``lifespan``) рядом с index_poller; на одном
uvicorn-воркере (см. корневой CLAUDE.md) лидер-выбор не требуется.
"""

import asyncio
from collections.abc import Awaitable, Callable

import openai
from sqlalchemy import select

from app.core.config import settings
from app.db.models.org_index import OrgIndex, INDEX_FAILED, INDEX_READY
from app.db.session import AsyncSessionLocal

from rag.create_index import touch_index


def _is_not_found(exc: Exception) -> bool:
    """Ошибка означает «стора больше нет» (истёк по TTL или удалён), а не временный сбой."""
    return (
        isinstance(exc, openai.NotFoundError)
        or getattr(exc, "status_code", None) == 404
    )


async def _mark_failed(index_id: int, error_message: str) -> None:
    async with AsyncSessionLocal() as db:
        idx = await db.get(OrgIndex, index_id)
        # Guard: трогаем только всё ещё ready-строку (не building/failed/удалённую).
        if idx is None or idx.status != INDEX_READY:
            return
        idx.status = INDEX_FAILED
        idx.error_message = error_message
        await db.commit()


async def keepalive_sweep(
    touch: Callable[[str, str], Awaitable[None]] = touch_index,
) -> None:
    """Один проход keep-alive по всем ready-индексам со стором.

    Публичная (можно дёрнуть из теста/крона). ``touch`` инъектируется в тестах,
    чтобы не ходить в AI Studio.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OrgIndex).where(
                OrgIndex.status == INDEX_READY,
                OrgIndex.vector_store_id.is_not(None),
            )
        )
        # Снимаем нужные поля до закрытия сессии — дальше только сеть, без залоченной сессии.
        # Guard `is not None` дублирует WHERE и заодно сужает тип для mypy (str, не str | None).
        rows = [
            (i.id, i.vector_store_id)
            for i in result.scalars().all()
            if i.vector_store_id is not None
        ]

    for index_id, vector_store_id in rows:
        try:
            await touch(vector_store_id, settings.INDEX_KEEPALIVE_QUERY)
        except Exception as e:  # noqa: BLE001 — одна плохая строка не должна убить проход
            if _is_not_found(e):
                await _mark_failed(index_id, "vector store expired or was deleted")
            else:
                # Временная ошибка AI Studio/сети — не роняем строку, повторим в след. цикле.
                print(f"[index_keepalive] touch index {index_id} failed: {e}")


async def index_keepalive_loop(stop_event: asyncio.Event) -> None:
    """Крутится, пока не выставлен stop_event (при остановке приложения)."""
    print("[index_keepalive] started")
    while not stop_event.is_set():
        try:
            await keepalive_sweep()
        except Exception as e:  # noqa: BLE001
            print(f"[index_keepalive] cycle error: {e}")

        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.INDEX_KEEPALIVE_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            pass  # обычный тик — идём на следующий проход
    print("[index_keepalive] stopped")
