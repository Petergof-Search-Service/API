from openai import AsyncOpenAI

from .config import settings


def _make_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )


async def delete_rag_file(stem: str) -> None:
    """Find and delete chunks file from Yandex Files API and all vector stores.

    stem = Path(system_key).stem, e.g. 'abc123_myfile'
    The corresponding chunks file is named '{stem}.chunks.jsonl'.
    """
    upload_name = f"{stem}.chunks.jsonl"
    client = _make_client()

    all_files = await client.files.list()
    file_ids = [f.id for f in all_files.data if f.filename == upload_name]

    if not file_ids:
        return

    vector_stores = await client.vector_stores.list()
    for vs in vector_stores.data:
        vs_files = await client.vector_stores.files.list(vs.id)
        for vsf in vs_files.data:
            if vsf.id in file_ids:
                try:
                    await client.vector_stores.files.delete(vs.id, vsf.id)
                except Exception:
                    pass

    for file_id in file_ids:
        try:
            await client.files.delete(file_id)
        except Exception:
            pass
