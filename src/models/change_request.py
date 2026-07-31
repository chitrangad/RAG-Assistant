"""ChangeRequest and ProjectChangeRequest models."""

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


class ChangeRequest(Base):
    """A change request extracted from documents."""

    __tablename__ = "change_requests"

    id: Mapped[str] = pk_column()
    cr_number: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    title: Mapped[str | None] = optional_string_column()
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]
    updated_at: Mapped[datetime] = updated_at_column()  # type: ignore[assignment]

    project_links: Mapped[list["ProjectChangeRequest"]] = relationship(
        back_populates="change_request", cascade="all, delete-orphan"
    )


class ProjectChangeRequest(Base):
    """Links a change request to a project."""

    __tablename__ = "project_change_requests"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "change_request_id", name="uq_project_cr"
        ),
    )

    id: Mapped[str] = pk_column()
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    change_request_id: Mapped[str] = mapped_column(
        ForeignKey("change_requests.id", ondelete="CASCADE"), nullable=False
    )
    match_confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]

    project: Mapped["Project"] = relationship(back_populates="change_requests")
    change_request: Mapped["ChangeRequest"] = relationship(
        back_populates="project_links"
    )
