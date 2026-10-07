"""Тесты keep-alive индексов (app/core/index_keepalive.py).

Петля работает через ``AsyncSessionLocal`` напрямую (не через ``Depends(get_db)``),
поэтому подменяем его на in-memory SQLite и инъектируем фейковый ``touch`` вместо
похода в AI Studio.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.db.models as _models  # noqa: F401  регистрирует таблицы в Base.metadata
from app.core import index_keepalive
from app.db import Base
from app.db.models.org_index import (
    INDEX_BUILDING,
    INDEX_FAILED,
    INDEX_READY,
    OrgIndex,
)


class _NotFound(Exception):
    """Имитирует 404 от AI Studio (как openai.NotFoundError по status_code)."""

    status_code = 404


@pytest_asyncio.fixture
async def maker(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    # keepalive_sweep/_mark_failed ходят в БД через модульный AsyncSessionLocal.
    monkeypatch.setattr(index_keepalive, "AsyncSessionLocal", sm)
    try:
        yield sm
    finally:
        await engine.dispose()


async def _add_index(
    sm: async_sessionmaker[AsyncSession],
    *,
    status: str,
    vector_store_id: str | None = "vs_1",
    name: str = "idx",
) -> int:
    async with sm() as s:
        idx = OrgIndex(
            org_id=1, name=name, status=status, vector_store_id=vector_store_id
        )
        s.add(idx)
        await s.commit()
        await s.refresh(idx)
        return idx.id


async def _get(
    sm: async_sessionmaker[AsyncSession], index_id: int
) -> tuple[str, str | None]:
    async with sm() as s:
        idx = await s.get(OrgIndex, index_id)
        assert idx is not None
        return idx.status, idx.error_message


async def test_sweep_touches_ready_index(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    index_id = await _add_index(maker, status=INDEX_READY, vector_store_id="vs_live")
    touched: list[tuple[str, str]] = []

    async def fake_touch(vs_id: str, query: str) -> None:
        touched.append((vs_id, query))

    await index_keepalive.keepalive_sweep(touch=fake_touch)

    assert touched == [("vs_live", index_keepalive.settings.INDEX_KEEPALIVE_QUERY)]
    status, _ = await _get(maker, index_id)
    assert status == INDEX_READY


async def test_sweep_skips_building_failed_and_storeless(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    await _add_index(maker, status=INDEX_BUILDING, vector_store_id="vs_b")
    await _add_index(maker, status=INDEX_FAILED, vector_store_id="vs_f")
    # ready без стора — пинговать нечего.
    await _add_index(maker, status=INDEX_READY, vector_store_id=None)
    touched: list[str] = []

    async def fake_touch(vs_id: str, query: str) -> None:
        touched.append(vs_id)

    await index_keepalive.keepalive_sweep(touch=fake_touch)

    assert touched == []


async def test_sweep_marks_failed_on_not_found(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    index_id = await _add_index(maker, status=INDEX_READY, vector_store_id="vs_gone")

    async def fake_touch(vs_id: str, query: str) -> None:
        raise _NotFound()

    await index_keepalive.keepalive_sweep(touch=fake_touch)

    status, error = await _get(maker, index_id)
    assert status == INDEX_FAILED
    assert error is not None and "expired" in error


async def test_sweep_keeps_ready_on_transient_error(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    index_id = await _add_index(maker, status=INDEX_READY, vector_store_id="vs_flaky")

    async def fake_touch(vs_id: str, query: str) -> None:
        raise RuntimeError("timeout")

    await index_keepalive.keepalive_sweep(touch=fake_touch)

    status, _ = await _get(maker, index_id)
    assert status == INDEX_READY
