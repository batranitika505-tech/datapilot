from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.datasets import router as datasets_router

from app.database import engine

app = FastAPI(
    title="DataPilot AI",
    description="Evidence-driven AI data investigation platform",
    version="0.1.0"
)
app.include_router(datasets_router)


@app.get("/")
def home():
    return {
        "message": "Welcome to DataPilot AI!"
    }


@app.get("/health/db")
def database_health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected"
        }

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed"
        )