"""IngestionRun model — tracks ingestion jobs."""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import (
    Base,
    pk_column,
    optional_string_column,
)


class IngestionRun(Base):
    """Tracks an ingestion run for a data source."""

    __tablename__ = "ingestion_runs"

    id: Mapped[str] = pk_column()
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    documents_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    documents_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    documents_indexed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped["DataSource"] = relationship(back_populates="ingestion_runs")
