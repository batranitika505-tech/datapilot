import uuid
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Dataset
from app.profiling import profile_dataframe
from app.schemas import DatasetDetail, DatasetSummary

router = APIRouter(
    prefix="/api/datasets",
    tags=["Datasets"]
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"

@router.post("/inspect")
async def inspect_csv(file: UploadFile = File(...)):

    # 1. Check the filename
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed"
        )

    # 2. Read the uploaded file
    contents = await file.read(MAX_FILE_SIZE + 1)

    # 3. Check file size
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size must not exceed 10 MB"
        )

    # 4. Check whether file is empty
    if not contents:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty"
        )

    # 5. Read CSV using Pandas
    try:
        df = pd.read_csv(BytesIO(contents))

    except pd.errors.EmptyDataError:
        raise HTTPException(
            status_code=400,
            detail="CSV contains no data or column headers"
        )

    except (pd.errors.ParserError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail="Invalid CSV format or encoding"
        )

    # 6. Check whether the CSV has columns
    if len(df.columns) == 0:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain at least one column"
        )

    # 7. Extract column information
    columns = []

    for column in df.columns:
        columns.append({
            "name": str(column),
            "data_type": str(df[column].dtype)
        })

    # 8. Return dataset information
    return {
        "filename": file.filename,
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "columns": columns,
        "profile": profile_dataframe(df)
    }

@router.post("/upload", response_model=DatasetDetail, status_code=201)
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 1. Validate filename
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed"
        )

    if len(file.filename) > 255:
        raise HTTPException(
            status_code=400,
            detail="Filename must not exceed 255 characters"
        )

    try:
        # 2. Read and validate file size
        contents = await file.read(MAX_FILE_SIZE + 1)

        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="File size must not exceed 10 MB"
            )

        if not contents:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty"
            )

        # 3. Parse CSV
        try:
            df = pd.read_csv(BytesIO(contents))
        except pd.errors.EmptyDataError:
            raise HTTPException(
                status_code=400,
                detail="CSV contains no data or column headers"
            )
        except (pd.errors.ParserError, UnicodeDecodeError):
            raise HTTPException(
                status_code=400,
                detail="Invalid CSV format or encoding"
            )

        if len(df.columns) == 0:
            raise HTTPException(
                status_code=400,
                detail="CSV must contain at least one column"
            )

        # 4. Generate column metadata and profile
        columns = [
            {
                "name": str(column),
                "data_type": str(df[column].dtype)
            }
            for column in df.columns
        ]

        profile = profile_dataframe(df)

        # 5. Generate a unique storage filename
        dataset_id = uuid4()
        storage_filename = f"{dataset_id}.csv"

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        storage_path = UPLOAD_DIR / storage_filename
        try:
            relative_storage_path = storage_path.relative_to(PROJECT_ROOT)
        except ValueError:
            try:
                relative_storage_path = storage_path.resolve().relative_to(PROJECT_ROOT.resolve())
            except ValueError:
                relative_storage_path = storage_path.resolve()

        # 6. Save CSV file
        storage_path.write_bytes(contents)

        try:
            # 7. Save dataset metadata in PostgreSQL
            dataset = Dataset(
                id=dataset_id,
                filename=file.filename,
                storage_path=str(relative_storage_path),
                total_rows=len(df),
                total_columns=len(df.columns),
                columns=columns,
                profile=profile
            )

            db.add(dataset)
            db.commit()
            db.refresh(dataset)

        except SQLAlchemyError:
            db.rollback()

            if storage_path.exists():
                storage_path.unlink()

            raise HTTPException(
                status_code=500,
                detail="Failed to save dataset metadata"
            )

        # 8. Return saved dataset details
        return dataset

    except HTTPException:
        raise

    except OSError:
        raise HTTPException(
            status_code=500,
            detail="Failed to store uploaded CSV file"
        )

    finally:
        await file.close()
@router.get("/", response_model=list[DatasetSummary])
def list_datasets(db: Session = Depends(get_db)):
    statement = select(Dataset).order_by(Dataset.created_at.desc())

    result = db.execute(statement)

    return result.scalars().all()

@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    dataset = db.get(Dataset, dataset_id)

    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail="Dataset not found"
        )

    return dataset

