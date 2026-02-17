import os
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()
YANDEX_API_KEY = os.getenv("YC_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YC_FOLDER_ID")


async def create_index(name, input_file_ids):
    client = AsyncOpenAI(
        api_key=YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
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
        'name': name,
        'vector_store_id': vector_store_id,
        'status': vector_store.status
    }