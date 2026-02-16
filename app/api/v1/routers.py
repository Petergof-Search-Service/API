from fastapi import APIRouter

from app.api.v1.endpoints import rag_router, auth_router, statistic_router, index_router, \
    settings_router

api_router = APIRouter()
api_router.include_router(rag_router, tags=["Rag endpoints"])

api_router.include_router(auth_router, tags=["API auth"])

api_router.include_router(statistic_router, tags=["Statistic endpoints"])

api_router.include_router(index_router, tags=["Index endpoints"])

api_router.include_router(settings_router, tags=["Settings endpoints"])
