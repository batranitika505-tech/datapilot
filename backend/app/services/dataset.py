from io import BytesIO
from pathlib import Path
from typing import Sequence
import uuid
from uuid import uuid4

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Dataset
from app.profiling import profile_dataframe

# Storage defaults
PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"


class DatasetServiceError(Exception):
    """Base exception for all dataset service errors."""


class DatasetValidationError(DatasetServiceError):
    """Raised when CSV validation fails (empty, malformed, invalid columns)."""


class DatasetNotFoundError(DatasetServiceError):
    """Raised when a requested dataset does not exist."""


class DatasetStorageError(DatasetServiceError):
    """Raised when writing the file to disk fails (OSError)."""


class DatasetDatabaseError(DatasetServiceError):
    """Raised when database persistence fails (SQLAlchemyError)."""


def parse_and_profile_csv(contents: bytes) -> tuple[pd.DataFrame, list[dict], dict]:
    """
    Parse CSV bytes, extract column information, and profile dataset statistics.

    Raises:
        DatasetValidationError: If CSV is empty, malformed, unparseable, or contains 0 columns.
    """
    try:
        df = pd.read_csv(BytesIO(contents))
    except pd.errors.EmptyDataError:
        raise DatasetValidationError("CSV contains no data or column headers")
    except (pd.errors.ParserError, UnicodeDecodeError):
        raise DatasetValidationError("Invalid CSV format or encoding")

    if len(df.columns) == 0:
        raise DatasetValidationError("CSV must contain at least one column")

    columns = [
        {
            "name": str(column),
            "data_type": str(df[column].dtype),
        }
        for column in df.columns
    ]

    profile = profile_dataframe(df)
    return df, columns, profile


def inspect_dataset(contents: bytes, filename: str) -> dict:
    """
    Inspect a CSV dataset without persisting it to disk or database.

    Returns dataset summary dictionary with columns and profiling information.
    """
    df, columns, profile = parse_and_profile_csv(contents)
    return {
        "filename": filename,
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "columns": columns,
        "profile": profile,
    }


def create_dataset(
    db: Session,
    contents: bytes,
    filename: str,
    upload_dir: Path | None = None,
    project_root: Path | None = None,
) -> Dataset:
    """
    Process, store, and persist a new dataset.

    Steps:
    1. Parse and validate CSV data.
    2. Write file contents to disk at upload_dir / {dataset_id}.csv.
    3. Compute normalized relative storage path (fallback to resolved path if outside project_root).
    4. Persist metadata in PostgreSQL database.
    5. On SQLAlchemyError, rollback transaction and remove the newly created file.
    """
    df, columns, profile = parse_and_profile_csv(contents)

    target_upload_dir = upload_dir if upload_dir is not None else UPLOAD_DIR
    target_project_root = project_root if project_root is not None else PROJECT_ROOT

    dataset_id = uuid4()
    storage_filename = f"{dataset_id}.csv"

    try:
        target_upload_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatasetStorageError("Failed to store uploaded CSV file") from exc

    storage_path = target_upload_dir / storage_filename
    try:
        relative_storage_path = storage_path.relative_to(target_project_root)
    except ValueError:
        try:
            relative_storage_path = storage_path.resolve().relative_to(target_project_root.resolve())
        except ValueError:
            relative_storage_path = storage_path.resolve()

    file_created = False
    try:
        with open(storage_path, "xb") as f:
            file_created = True
            f.write(contents)
    except OSError as exc:
        if file_created:
            try:
                if storage_path.exists():
                    storage_path.unlink()
            except OSError:
                pass
        raise DatasetStorageError("Failed to store uploaded CSV file") from exc

    try:
        dataset = Dataset(
            id=dataset_id,
            filename=filename,
            storage_path=str(relative_storage_path),
            total_rows=len(df),
            total_columns=len(df.columns),
            columns=columns,
            profile=profile,
        )

        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        return dataset
    except SQLAlchemyError as exc:
        try:
            db.rollback()
        except Exception:
            pass

        if file_created:
            try:
                if storage_path.exists():
                    storage_path.unlink()
            except OSError:
                pass
        raise DatasetDatabaseError("Failed to save dataset metadata") from exc


def list_datasets(db: Session) -> Sequence[Dataset]:
    """Retrieve all datasets ordered by created_at descending."""
    statement = select(Dataset).order_by(Dataset.created_at.desc())
    try:
        result = db.execute(statement)
        return result.scalars().all()
    except SQLAlchemyError as exc:
        raise DatasetDatabaseError("Failed to retrieve datasets") from exc


def get_dataset(db: Session, dataset_id: uuid.UUID) -> Dataset | None:
    """Retrieve a dataset by its UUID, or None if not found."""
    try:
        return db.get(Dataset, dataset_id)
    except SQLAlchemyError as exc:
        raise DatasetDatabaseError("Failed to retrieve dataset") from exc
