from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import boto3

from app.core.config import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

S3_UPLOAD_PREFIX = "incoming"
PRESIGNED_EXPIRES_IN = 3600


def make_s3_client() -> S3Client:
    return boto3.client(
        service_name="s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
    )


def delete_s3_objects(keys: list[str]) -> None:
    client = make_s3_client()
    for key in keys:
        try:
            client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
        except Exception:
            pass


def generate_upload_presigned_url(filename: str) -> tuple[str, str]:
    """
    Генерирует presigned URL для загрузки файла в S3 (PUT).
    Возвращает (upload_url, s3_key).
    """
    if not filename or not filename.strip():
        raise ValueError("filename is required")

    s3_key = f"{S3_UPLOAD_PREFIX}/{uuid.uuid4().hex}_{filename.strip()}"
    client = make_s3_client()
    # ContentType должен совпадать с заголовком, который шлёт фронт при PUT, иначе 403.
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.S3_BUCKET_NAME,
            "Key": s3_key,
            "ContentType": "application/pdf",
        },
        ExpiresIn=PRESIGNED_EXPIRES_IN,
    )
    return url, s3_key
