from typing import Any

from openai import AsyncOpenAI

from .config import settings


def _make_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )


async def create_vector_store(name: str, input_file_ids: list[str]) -> str:
    """Создаёт vector store в AI Studio и СРАЗУ возвращает его id.

    Не ждёт завершения сборки: стор возвращается в статусе ``in_progress``,
    а готовность потом отслеживает поллер через :func:`retrieve_index`.
    Раньше здесь был busy-poll ``while True: retrieve; sleep(3)`` — он держал
    воркер и не переживал редеплой; теперь ожидание вынесено из запроса.
    """
    client = _make_client()
    vector_store = await client.vector_stores.create(
        name=name,
        expires_after={"anchor": "last_active_at", "days": 30},
        file_ids=input_file_ids,
    )
    return str(vector_store.id)


async def retrieve_index(vector_store_id: str) -> dict[str, Any]:
    """Текущее состояние стора: ``{"status": str, "file_counts": dict | None}``.

    status: ``in_progress`` | ``completed`` | ``failed`` | ``expired``.
    file_counts: ``{in_progress, completed, failed, cancelled, total}`` или None.
    """
    client = _make_client()
    vs = await client.vector_stores.retrieve(vector_store_id)

    file_counts = getattr(vs, "file_counts", None)
    if file_counts is not None and not isinstance(file_counts, dict):
        # openai SDK отдаёт pydantic-модель — приводим к обычному dict для JSON-колонки
        file_counts = file_counts.model_dump()

    return {"status": vs.status, "file_counts": file_counts}


async def delete_index(vector_store_id: str) -> None:
    """Удаляет vector store в AI Studio."""
    client = _make_client()
    await client.vector_stores.delete(vector_store_id)
