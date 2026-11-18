from fastapi import FastAPI

from app.api import api_router


def create_app() -> FastAPI:
    """Application factory for DataPilot AI."""
    app = FastAPI(
        title="DataPilot AI",
        description="Evidence-driven AI data investigation platform",
        version="0.1.0",
    )
    app.include_router(api_router)
    return app


# ASGI entrypoint
app = create_app()
