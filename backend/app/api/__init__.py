from fastapi import APIRouter

from app.api.datasets import router as datasets_router
from app.api.system import router as system_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(datasets_router)

__all__ = ["api_router", "system_router", "datasets_router"]

