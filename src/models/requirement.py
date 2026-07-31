"""Requirement and ProjectRequirement models."""

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


class Requirement(Base):
    """A requirement extracted from documents."""

    __tablename__ = "requirements"

    id: Mapped[str] = pk_column()
    requirement_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    title: Mapped[str | None] = optional_string_column()
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]
    updated_at: Mapped[datetime] = updated_at_column()  # type: ignore[assignment]

    # Relationships
    project_links: Mapped[list["ProjectRequirement"]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan"
    )


class ProjectRequirement(Base):
    """Links a requirement to a project."""

    __tablename__ = "project_requirements"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "requirement_id", name="uq_project_requirement"
        ),
    )

    id: Mapped[str] = pk_column()
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False
    )
    match_confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]

    project: Mapped["Project"] = relationship(back_populates="requirements")
    requirement: Mapped["Requirement"] = relationship(back_populates="project_links")
