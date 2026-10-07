"""Пересоздание файла chunks.jsonl в AI Studio из durable-источника в S3.

Файлы в AI Studio истекают по TTL и пропадают; когда админ собирает индекс, файла
может уже не быть. RAG-функция (репо RAG) складывает готовый ``{stem}.chunks.jsonl``
в ``RAG_CHUNKS_STORE_PATH`` бакета, а здесь мы читаем его и заливаем заново —
по требованию, в момент сборки индекса (см. endpoints/index.py).
"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING, cast

import boto3
from openai import AsyncOpenAI

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

from .config import settings


def make_s3_client() -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=settings.RAG_S3_ENDPOINT_URL,
        aws_access_key_id=settings.RAG_ACCESS_KEY,
        aws_secret_access_key=settings.RAG_SECRET_KEY,
    )


def _get_chunks_bytes(s3_client: S3Client, key: str) -> bytes | None:
    """Читает chunks.jsonl из S3. None, если объекта нет."""
    try:
        obj = s3_client.get_object(Bucket=settings.RAG_BUCKET_NAME, Key=key)
    except s3_client.exceptions.NoSuchKey:
        return None
    return cast(bytes, obj["Body"].read())


async def ensure_chunks_file(stem: str) -> str | None:
    """Заливает ``{stem}.chunks.jsonl`` из S3 в AI Studio, возвращает file_id.

    None, если durable-артефакта в S3 нет (нечем пересоздать). Без ``expires_after``
    — файл не самоистекает; при следующей пропаже его снова пересоздадут отсюда.
    """
    upload_name = f"{stem}.chunks.jsonl"
    s3_key = f"{settings.RAG_CHUNKS_STORE_PATH.rstrip('/')}/{upload_name}"

    s3_client = make_s3_client()
    jsonl_data = await asyncio.to_thread(_get_chunks_bytes, s3_client, s3_key)
    if jsonl_data is None:
        return None

    client = AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )
    bio = io.BytesIO(jsonl_data)
    bio.name = upload_name
    f = await client.files.create(
        file=(upload_name, bio, "application/jsonlines"),
        purpose="assistants",
        extra_body={"format": "chunks"},
    )
    return cast(str, f.id)
