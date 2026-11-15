from io import BytesIO

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.profiling import profile_dataframe

router = APIRouter(
    prefix="/api/datasets",
    tags=["Datasets"]
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


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
