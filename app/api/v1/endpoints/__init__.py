from .rag import router as rag_router
from .auth import router as auth_router
from .statistic import router as statistic_router
from .index import router as index_router
from .settings import router as settings_router

__all__ = [rag_router, auth_router, statistic_router, index_router, settings_router]
