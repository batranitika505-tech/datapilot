from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import api_router
from app.database import engine

logger = logging.getLogger(__name__)


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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    app.include_router(api_router)
    return app


# ASGI entrypoint
app = create_app()
