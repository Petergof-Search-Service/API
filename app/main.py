import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api import v1_router
from app.core.index_keepalive import index_keepalive_loop
from app.core.index_poller import index_poller_loop
from app.core.rate_limit import limiter


def _rate_limit_handler(request: Request, exc: Exception) -> Response:
    # slowapi типизирует хендлер под RateLimitExceeded, а add_exception_handler
    # ждёт Callable[..., Exception]; сужаем тип (сюда попадает только RateLimitExceeded).
    return _rate_limit_exceeded_handler(request, cast(RateLimitExceeded, exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Два фоновых цикла, оба durable в БД и безопасны к редеплою:
    #  - index_poller: двигает building → ready|failed (сборка не шлёт вебхуков);
    #  - index_keepalive: search-пинг по ready-индексам, иначе стор истекает по TTL.
    stop_event = asyncio.Event()
    poller_task = asyncio.create_task(index_poller_loop(stop_event))
    keepalive_task = asyncio.create_task(index_keepalive_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        poller_task.cancel()
        keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller_task
        with contextlib.suppress(asyncio.CancelledError):
            await keepalive_task


app = FastAPI(lifespan=lifespan)

# Rate limiting (slowapi): лимитер, обработчик 429 и middleware, применяющее
# лимиты, объявленные декораторами @limiter.limit(...) на эндпоинтах.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix="/api/v1")
