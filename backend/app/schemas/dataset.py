from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DatasetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    total_rows: int
    total_columns: int
    created_at: datetime


class DatasetDetail(DatasetSummary):
    columns: list[dict]
    profile: dict
