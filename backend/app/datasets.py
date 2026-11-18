"""
Backward-compatibility module for app.datasets.
Re-exports router and dataset symbols from the canonical app.api.datasets module.
"""

from app.api.datasets import (
    MAX_FILE_SIZE,
    PROJECT_ROOT,
    UPLOAD_DIR,
    get_dataset,
    inspect_csv,
    list_datasets,
    router,
    upload_csv,
)

__all__ = [
    "router",
    "MAX_FILE_SIZE",
    "PROJECT_ROOT",
    "UPLOAD_DIR",
    "inspect_csv",
    "upload_csv",
    "list_datasets",
    "get_dataset",
]
