from openai import AsyncOpenAI

from .config import settings


async def get_indexes(to_sort: bool = False) -> list[str]:
    """
    Возвращает список названий всех индексов
    names = ['name1', 'name2', ..., 'nameN']
    По умолчанию возвращает в порядке создания индексов.
    """
    client = AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )

    vector_stores = await client.vector_stores.list()
    names = []
    for i in vector_stores.data:
        names.append(i.name)

    if to_sort:
        names = list(sorted(names))

    return names


async def get_indexes_names2ids(to_sort: bool = False) -> dict[str, str]:
    """
    Возвращает словарь names2ids
    names = {'name1':'id1', 'name2':'id2', ...}
    """
    client = AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )

    vector_stores = await client.vector_stores.list()
    res = {}
    for i in vector_stores.data:
        res[i.name] = i.id

    return res
