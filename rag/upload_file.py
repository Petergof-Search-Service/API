from __future__ import annotations

import asyncio
import io
import json
import os
import re
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, cast

import boto3
import openai

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
from openai import AsyncOpenAI

from .config import settings


def make_s3_client() -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=settings.RAG_S3_ENDPOINT_URL,
        aws_access_key_id=settings.RAG_ACCESS_KEY,
        aws_secret_access_key=settings.RAG_SECRET_KEY,
    )


async def s3_get_bytes(s3_client: S3Client, key: str) -> bytes:
    def _sync() -> bytes:
        obj = s3_client.get_object(Bucket=settings.RAG_BUCKET_NAME, Key=key)
        return obj["Body"].read()

    return await asyncio.to_thread(_sync)


def parse_pages_from_bytes(data: bytes, key: str) -> List[Dict[str, Any]]:
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Не удалось распарсить JSON из {key}: {e}")

    if not (isinstance(obj, dict) and isinstance(obj.get("data"), list)):
        raise ValueError(
            f"Неожиданный формат файла {key}. Ожидал dict с полем 'data' (list)."
        )

    merged: List[Dict[str, Any]] = []

    for item in obj["data"]:
        if not isinstance(item, dict):
            continue
        if "page" not in item:
            continue

        try:
            page = int(item["page"])
        except Exception:
            continue

        text = str(item.get("text", "") or "").strip()
        if not text:
            continue

        if merged and merged[-1]["page"] == page:
            merged[-1]["text"] = (merged[-1]["text"] + "\n" + text).strip()
        else:
            merged.append({"page": page, "text": text})

    by_page: Dict[int, List[str]] = {}
    for p in merged:
        by_page.setdefault(p["page"], []).append(p["text"])

    pages = [
        {"page": page, "text": "\n".join(parts).strip()}
        for page, parts in by_page.items()
    ]
    pages.sort(key=lambda x: cast(int, x["page"]))
    return pages


def build_marked_text(pages: List[Dict[str, Any]]) -> str:
    parts = []
    for item in pages:
        p = item["page"]
        t = item["text"]
        parts.append(f"[PAGE {p}]\n{t}\n")
    return "\n".join(parts).strip() + "\n"


def _extract_page_markers_with_pos(text: str) -> List[Tuple[int, int]]:
    markers: List[Tuple[int, int]] = []
    for m in settings.RAG_PAGE_MARK_RE.finditer(text):
        markers.append((m.start(), int(m.group(1))))
    return markers


def _pages_for_slice(markers: List[Tuple[int, int]], start: int, end: int) -> List[int]:
    pages_in: List[int] = []
    seen = set()

    for pos, page in markers:
        if start <= pos < end:
            if page not in seen:
                seen.add(page)
                pages_in.append(page)

    if pages_in:
        return pages_in

    last_page = None
    for pos, page in markers:
        if pos < start:
            last_page = page
        else:
            break

    return [last_page] if last_page is not None else []


def _pages_header(pages: List[int]) -> str:
    if not pages:
        return "PAGES: unknown"
    if len(pages) == 1:
        return f"PAGES: {pages[0]}"
    return f"PAGES: {pages[0]}-{pages[-1]}"


def _strip_page_markers(fragment: str) -> str:
    cleaned = settings.RAG_PAGE_MARK_REMOVE_RE.sub("\n", fragment)
    # нормализуем лишние пустые строки
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def chunk_text_window_overlap(
    marked_text: str,
    window_chars: int,
    overlap_chars: int,
) -> List[Dict[str, str]]:
    if window_chars <= 0:
        raise ValueError("window_chars должен быть > 0")
    if overlap_chars < 0:
        raise ValueError("overlap_chars должен быть >= 0")
    if overlap_chars >= window_chars:
        raise ValueError("overlap_chars должен быть < window_chars")

    window_chars = min(window_chars, settings.RAG_MAX_CHUNK_LEN)
    step = window_chars - overlap_chars

    markers = _extract_page_markers_with_pos(marked_text)

    chunks: List[Dict[str, str]] = []
    n = len(marked_text)
    start = 0

    while start < n:
        end = min(start + window_chars, n)

        raw_fragment = marked_text[start:end]
        cleaned_fragment = _strip_page_markers(raw_fragment)

        if cleaned_fragment:
            pages = _pages_for_slice(markers, start, end)
            header = _pages_header(pages)

            body = f"{header}\n{cleaned_fragment}".strip()

            if len(body) > settings.RAG_MAX_CHUNK_LEN:
                allowed = settings.RAG_MAX_CHUNK_LEN - len(header) - 1
                trimmed = cleaned_fragment[: max(0, allowed)].rstrip()
                body = f"{header}\n{trimmed}".strip()

            chunks.append({"body": body})

        if end == n:
            break
        start += step

    return chunks


def chunks_to_jsonl_bytes(chunks: List[Dict[str, str]]) -> bytes:
    return (
        ("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks)) + "\n"
    ).encode("utf-8")


def make_upload_name(original_filename: str) -> str:
    base = os.path.basename(original_filename)
    name, _ext = os.path.splitext(base)
    return f"{name}.chunks.jsonl"


async def upload_chunks_jsonl_bytes(
    client: AsyncOpenAI,
    jsonl_data: bytes,
    upload_name: str,
    expires_seconds: int = 3600,
) -> str:
    bio = io.BytesIO(jsonl_data)
    bio.name = upload_name

    f = await client.files.create(
        file=(upload_name, bio, "application/jsonlines"),
        purpose="assistants",
        expires_after=openai.types.file_create_params.ExpiresAfter(
            anchor="created_at",
            seconds=expires_seconds,
        ),
        extra_body={"format": "chunks"},
    )
    return cast(str, f.id)


async def upload_file(
    filename: str,
    window_chars: int = 400,
    overlap_chars: int = 50,
) -> Dict[str, Any]:
    s3_key = (
        filename
        if filename.startswith(settings.RAG_CHUNKS_PATH.rstrip("/") + "/")
        else f"{settings.RAG_CHUNKS_PATH.rstrip('/')}/{filename}"
    )

    s3_client = make_s3_client()
    client = AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )

    raw = await s3_get_bytes(s3_client, s3_key)
    pages = parse_pages_from_bytes(raw, s3_key)

    marked = build_marked_text(pages)
    chunks = chunk_text_window_overlap(marked, window_chars, overlap_chars)
    jsonl_data = chunks_to_jsonl_bytes(chunks)

    upload_name = make_upload_name(s3_key)
    file_id = await upload_chunks_jsonl_bytes(client, jsonl_data, upload_name)

    print(f"OK: {s3_key} -> chunks={len(chunks)} -> file_id={file_id}")

    return {
        "s3_key": s3_key,
        "file_id": file_id,
        "chunks_count": len(chunks),
        "upload_name": upload_name,
    }
