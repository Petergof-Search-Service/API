"""Фоновый поллер статуса сборки индексов (замена busy-wait в запросе).

AI Studio не шлёт вебхуков о готовности vector store — статус можно узнать только
поллингом ``vector_stores.retrieve``. Раньше этим занималась asyncio-таска прямо в
обработчике ``POST /indexes`` (busy-poll ``while True: retrieve; sleep(3)``), из-за чего:
жила только в памяти процесса, держала глобальный лок и гибла при редеплое.

Теперь состояние сборки durable в БД (``indexes.status``), а этот поллер — единственная
петля, которая продвигает строки ``building → ready|failed``. Она поднимается в FastAPI
``lifespan`` (``app/main.py``); после редеплоя стартует заново и сама подхватывает
``building``-строки из БД — отдельный recovery-код не нужен.

Гонок за строки при будущем масштабировании избегаем через WHERE-guard
``status == building`` в UPDATE (переход делает только поллер, а удаление building
запрещено на уровне API), поэтому лидер-выбор пока не требуется.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.models.org_index import (
    OrgIndex,
    INDEX_BUILDING,
    INDEX_READY,
    INDEX_FAILED,
)
from app.db.session import AsyncSessionLocal

from rag.create_index import retrieve_index


def _age_seconds(ts: datetime) -> float:
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _all_files_failed(file_counts: dict | None) -> bool:
    """Все файлы упали при индексации (терминальная ошибка, даже если статус ещё in_progress)."""
    if not file_counts:
        return False
    total = int(file_counts.get("total", 0))
    failed = int(file_counts.get("failed", 0))
    in_progress = int(file_counts.get("in_progress", 0))
    return total > 0 and failed >= total and in_progress == 0


def _decide(
    vector_store_id: str | None, created_at: datetime, state: dict | None
) -> tuple[str | None, str | None, dict | None]:
    """Возвращает (new_status, error_message, file_counts) или (None, None, fc) если остаёмся building."""
    # Строка без стора: create не успел записать id (падение между flush и create).
    if not vector_store_id:
        if _age_seconds(created_at) > settings.INDEX_STALE_CREATE_SECONDS:
            return INDEX_FAILED, "vector store was never created", None
        return None, None, None

    status = state["status"] if state else None
    file_counts = state["file_counts"] if state else None

    # Терминальные провалы проверяем ДО completed: AI Studio выставляет
    # status=completed, даже если все файлы упали при векторизации, — иначе
    # пустой бесполезный стор показался бы «готовым».
    if _all_files_failed(file_counts):
        return INDEX_FAILED, "all files failed to index", file_counts
    if status in ("failed", "expired"):
        return INDEX_FAILED, f"vector store status: {status}", file_counts
    if status == "completed":
        return INDEX_READY, None, file_counts
    if _age_seconds(created_at) > settings.INDEX_BUILD_TIMEOUT_SECONDS:
        return INDEX_FAILED, "build timed out", file_counts

    # Всё ещё строится — обновим только прогресс (file_counts).
    return None, None, file_counts


async def _advance_one(
    index_id: int, vector_store_id: str | None, created_at: datetime
) -> None:
    state: dict | None = None
    if vector_store_id:
        try:
            state = await retrieve_index(vector_store_id)
        except Exception as e:
            # Временная ошибка AI Studio/сети — не роняем строку, повторим в след. цикле.
            # Но если билд уже слишком старый — фейлим, чтобы не висел вечно.
            if _age_seconds(created_at) > settings.INDEX_BUILD_TIMEOUT_SECONDS:
                await _apply(index_id, INDEX_FAILED, f"retrieve failed: {e}", None)
            return

    new_status, error_message, file_counts = _decide(vector_store_id, created_at, state)
    await _apply(index_id, new_status, error_message, file_counts)


async def _apply(
    index_id: int,
    new_status: str | None,
    error_message: str | None,
    file_counts: dict | None,
) -> None:
    async with AsyncSessionLocal() as db:
        idx = await db.get(OrgIndex, index_id)
        # Guard: обрабатываем только всё ещё строящиеся строки (не удалён/не переведён).
        if idx is None or idx.status != INDEX_BUILDING:
            return

        changed = False
        if file_counts is not None and idx.file_counts != file_counts:
            idx.file_counts = file_counts
            changed = True
        if new_status is not None:
            idx.status = new_status
            idx.error_message = error_message
            changed = True

        if changed:
            await db.commit()


async def _poll_once() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OrgIndex)
            .where(OrgIndex.status == INDEX_BUILDING)
            .order_by(OrgIndex.created_at)
            .limit(settings.INDEX_POLL_BATCH)
        )
        building = result.scalars().all()
        # Снимаем нужные поля до закрытия сессии — дальше только сеть, без залоченной сессии.
        rows = [(i.id, i.vector_store_id, i.created_at) for i in building]

    for index_id, vector_store_id, created_at in rows:
        try:
            await _advance_one(index_id, vector_store_id, created_at)
        except Exception as e:  # noqa: BLE001 — одна плохая строка не должна убить цикл
            print(f"[index_poller] failed to advance index {index_id}: {e}")


async def index_poller_loop(stop_event: asyncio.Event) -> None:
    """Крутится, пока не выставлен stop_event (при остановке приложения)."""
    print("[index_poller] started")
    while not stop_event.is_set():
        try:
            await _poll_once()
        except Exception as e:  # noqa: BLE001
            print(f"[index_poller] cycle error: {e}")

        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.INDEX_POLL_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            pass  # обычный тик — идём на следующий цикл
    print("[index_poller] stopped")
