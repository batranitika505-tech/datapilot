import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    storage_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False
    )

    total_rows: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    total_columns: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    columns: Mapped[list] = mapped_column(
        JSON,
        nullable=False
    )

    profile: Mapped[dict] = mapped_column(
        JSON,
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
