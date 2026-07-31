"""Document, ProjectDocument, DocumentChunk models."""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import (
    Base,
    pk_column,
    created_at_column,
    updated_at_column,
    optional_string_column,
    required_string_column,
)


class Document(Base):
    """An ingested document."""

    __tablename__ = "documents"

    id: Mapped[str] = pk_column()
    file_name: Mapped[str] = required_string_column()
    file_path: Mapped[str | None] = optional_string_column()
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]
    updated_at: Mapped[datetime] = updated_at_column()  # type: ignore[assignment]

    # Relationships
    project_links: Mapped[list["ProjectDocument"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    source_links: Mapped[list["SourceDocument"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ProjectDocument(Base):
    """Links a document to a project."""

    __tablename__ = "project_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "document_id", name="uq_project_document"),
    )

    id: Mapped[str] = pk_column()
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    relevance_score: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]

    project: Mapped["Project"] = relationship(back_populates="documents")
    document: Mapped["Document"] = relationship(back_populates="project_links")


class DocumentChunk(Base):
    """A chunked segment of a document with its embedding metadata."""

    __tablename__ = "document_chunks"

    id: Mapped[str] = pk_column()
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chroma_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]

    document: Mapped["Document"] = relationship(back_populates="chunks")
