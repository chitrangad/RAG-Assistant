"""Project, ProjectAlias models."""

from datetime import date, datetime
from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import (
    Base,
    pk_column,
    created_at_column,
    updated_at_column,
    optional_string_column,
    required_string_column,
)


class Project(Base):
    """A registered project in the catalog."""

    __tablename__ = "projects"

    id: Mapped[str] = pk_column()
    name: Mapped[str] = required_string_column()
    description: Mapped[str | None] = optional_string_column()
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    team_lead: Mapped[str | None] = optional_string_column()
    repository_url: Mapped[str | None] = optional_string_column()
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]
    updated_at: Mapped[datetime] = updated_at_column()  # type: ignore[assignment]

    # Relationships
    aliases: Mapped[list["ProjectAlias"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    requirements: Mapped[list["ProjectRequirement"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    change_requests: Mapped[list["ProjectChangeRequest"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    documents: Mapped[list["ProjectDocument"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["ProjectArtifact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectAlias(Base):
    """Alternative names / aliases for a project."""

    __tablename__ = "project_aliases"
    __table_args__ = (
        UniqueConstraint("project_id", "alias", name="uq_project_alias"),
    )

    id: Mapped[str] = pk_column()
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = required_string_column()
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]

    project: Mapped["Project"] = relationship(back_populates="aliases")
