"""DataSource and SourceDocument models."""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import (
    Base,
    pk_column,
    created_at_column,
    updated_at_column,
    optional_string_column,
    required_string_column,
)


class DataSource(Base):
    """A registered data source for ingestion."""

    __tablename__ = "data_sources"

    id: Mapped[str] = pk_column()
    name: Mapped[str] = required_string_column()
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    connection_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scan_mode: Mapped[str] = mapped_column(
        String(20), default="incremental", nullable=False
    )
    owner_email: Mapped[str | None] = optional_string_column()
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_by: Mapped[str | None] = optional_string_column()
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]
    updated_at: Mapped[datetime] = updated_at_column()  # type: ignore[assignment]

    documents: Mapped[list["SourceDocument"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    ingestion_runs: Mapped[list["IngestionRun"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class SourceDocument(Base):
    """Links a document to its source."""

    __tablename__ = "source_documents"

    id: Mapped[str] = pk_column()
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]

    source: Mapped["DataSource"] = relationship(back_populates="documents")
    document: Mapped["Document"] = relationship(back_populates="source_links")
