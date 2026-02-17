import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()
YANDEX_API_KEY = os.getenv("YC_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YC_FOLDER_ID")


async def get_files(to_sort=False):
    '''
    Возвращает список названий всех файлов
    names = ['name1', 'name2', ..., 'nameN']
    По умолчанию возвращает в порядке добавления файлов.
    '''
    client = AsyncOpenAI(
        api_key=YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    
    files_list = await client.files.list()
    filenames = []
    
    for i in files_list.data:
        filenames.append(i.filename)

    if to_sort:
        filenames = list(sorted(filenames))
    
    return filenames


async def get_files_names2ids(to_sort=False):
    '''
    Возвращает словарь names2ids
    names = {'name1':'id1', 'name2':'id2', ...}
    '''
    client = AsyncOpenAI(
        api_key=YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    
    files_list = await client.files.list()
    res = {}
    
    for i in files_list.data:
        res[i.filename] = i.id
    
    return res
    