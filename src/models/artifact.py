"""Artifact and ProjectArtifact models."""

from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import (
    Base,
    pk_column,
    created_at_column,
    updated_at_column,
    optional_string_column,
    required_string_column,
)


class Artifact(Base):
    """A discovered project artifact (file, repo, URL, etc.)."""

    __tablename__ = "artifacts"

    id: Mapped[str] = pk_column()
    artifact_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    name: Mapped[str] = required_string_column()
    location: Mapped[str | None] = optional_string_column()
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]
    updated_at: Mapped[datetime] = updated_at_column()  # type: ignore[assignment]

    project_links: Mapped[list["ProjectArtifact"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )


class ProjectArtifact(Base):
    """Links an artifact to a project."""

    __tablename__ = "project_artifacts"
    __table_args__ = (
        UniqueConstraint("project_id", "artifact_id", name="uq_project_artifact"),
    )

    id: Mapped[str] = pk_column()
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    match_confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]

    project: Mapped["Project"] = relationship(back_populates="artifacts")
    artifact: Mapped["Artifact"] = relationship(back_populates="project_links")
