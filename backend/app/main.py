from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api import api_router
from app.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Application startup
    try:
        yield
    finally:
        # Application shutdown: gracefully dispose database connections
        engine.dispose()


def create_app() -> FastAPI:
    """Application factory for DataPilot AI."""
    app = FastAPI(
        title="DataPilot AI",
        description="Evidence-driven AI data investigation platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(api_router)
    return app


# ASGI entrypoint
app = create_app()
