"""Тесты пересоздания файла chunks.jsonl в AI Studio из S3 (rag/upload_file.py).

S3 и AsyncOpenAI подменяем фейками — реальных вызовов нет.
"""

from __future__ import annotations

import io

import pytest

from rag import upload_file


class _FakeExceptions:
    class NoSuchKey(Exception):
        pass


class _FakeS3:
    def __init__(self, data: bytes | None) -> None:
        self._data = data
        self.exceptions = _FakeExceptions

    def get_object(self, Bucket: str, Key: str) -> dict:
        if self._data is None:
            raise self.exceptions.NoSuchKey()
        return {"Body": io.BytesIO(self._data)}


class _FakeFiles:
    def __init__(self, created: list[dict]) -> None:
        self._created = created

    async def create(self, **kwargs: object) -> object:
        self._created.append(kwargs)
        return type("_R", (), {"id": "file_new"})()


class _FakeClient:
    def __init__(self, created: list[dict]) -> None:
        self.files = _FakeFiles(created)


async def test_ensure_chunks_file_uploads_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict] = []
    monkeypatch.setattr(
        upload_file, "make_s3_client", lambda: _FakeS3(b'{"body":"x"}\n')
    )
    monkeypatch.setattr(upload_file, "AsyncOpenAI", lambda **kw: _FakeClient(created))

    file_id = await upload_file.ensure_chunks_file("abc_doc")

    assert file_id == "file_new"
    assert len(created) == 1
    assert created[0]["purpose"] == "assistants"
    # имя заливаемого файла = {stem}.chunks.jsonl
    assert created[0]["file"][0] == "abc_doc.chunks.jsonl"


async def test_ensure_chunks_file_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upload_file, "make_s3_client", lambda: _FakeS3(None))

    def _boom(**kw: object) -> object:
        raise AssertionError("AsyncOpenAI не должен вызываться без артефакта")

    monkeypatch.setattr(upload_file, "AsyncOpenAI", _boom)

    file_id = await upload_file.ensure_chunks_file("missing_doc")

    assert file_id is None
