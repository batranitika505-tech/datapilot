import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import DatasetDetail, DatasetSummary
from app.services import dataset as dataset_service
from app.services.dataset import (
    PROJECT_ROOT,
    UPLOAD_DIR,
    DatasetDatabaseError,
    DatasetStorageError,
    DatasetValidationError,
)

router = APIRouter(
    prefix="/api/datasets",
    tags=["Datasets"]
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/inspect")
async def inspect_csv(file: UploadFile = File(...)):
    # 1. Validate filename
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed"
        )

    try:
        # 2. Read contents up to max size + 1
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

        # 5. Delegate CSV parsing and profiling to service
        try:
            return dataset_service.inspect_dataset(contents, file.filename)
        except DatasetValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    finally:
        await file.close()


@router.post("/upload", response_model=DatasetDetail, status_code=201)
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 1. Validate filename extension and length
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
        # 2. Read contents up to max size + 1
        contents = await file.read(MAX_FILE_SIZE + 1)

        # 3. Validate size bounds
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

        # 4. Delegate parsing, storage, and persistence to service
        try:
            return dataset_service.create_dataset(
                db=db,
                contents=contents,
                filename=file.filename,
                upload_dir=UPLOAD_DIR,
                project_root=PROJECT_ROOT,
            )
        except DatasetValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except DatasetStorageError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        except DatasetDatabaseError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    finally:
        await file.close()


@router.get("/", response_model=list[DatasetSummary])
def list_datasets(db: Session = Depends(get_db)):
    try:
        return dataset_service.list_datasets(db)
    except DatasetDatabaseError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    try:
        dataset = dataset_service.get_dataset(db, dataset_id)
    except DatasetDatabaseError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail="Dataset not found"
        )
    return dataset
