import asyncio
from typing import Any
from openai import AsyncOpenAI
from .config import settings


async def create_index(name: str, input_file_ids: list[str]) -> dict[str, Any]:
    client = AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )

    print("Создаем поисковый индекс...")

    vector_store = await client.vector_stores.create(
        name=name,
        # metadata={"key": "value"},
        expires_after={"anchor": "last_active_at", "days": 30},
        file_ids=input_file_ids,
    )

    vector_store_id = vector_store.id
    print("Vector store создан:", vector_store_id)

    while True:
        vector_store = await client.vector_stores.retrieve(vector_store_id)
        print("Статус vector store:", vector_store.status)

        # in_progress — индекс строится
        # completed — готов
        # failed — ошибка
        if vector_store.status != "in_progress":
            break

        await asyncio.sleep(3)

    return {
        "name": name,
        "vector_store_id": vector_store_id,
        "status": vector_store.status,
    }
