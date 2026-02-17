from openai import AsyncOpenAI
from .config import settings


async def get_files(to_sort: bool = False) -> list[str]:
    """
    Возвращает список названий всех файлов
    names = ['name1', 'name2', ..., 'nameN']
    По умолчанию возвращает в порядке добавления файлов.
    """
    client = AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )

    files_list = await client.files.list()
    filenames = []

    for i in files_list.data:
        filenames.append(i.filename)

    if to_sort:
        filenames = list(sorted(filenames))

    return filenames


async def get_files_names2ids(to_sort: bool = False) -> dict[str, str]:
    """
    Возвращает словарь names2ids
    names = {'name1':'id1', 'name2':'id2', ...}
    """
    client = AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )

    files_list = await client.files.list()
    res = {}

    for i in files_list.data:
        res[i.filename] = i.id

    return res
