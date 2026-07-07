import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import v1_router
from app.core.index_poller import index_poller_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Фоновый поллер статуса сборки индексов. Состояние сборки durable в БД,
    # поэтому после редеплоя петля просто продолжает добивать building-строки.
    stop_event = asyncio.Event()
    poller_task = asyncio.create_task(index_poller_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        poller_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller_task


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix="/api/v1")
