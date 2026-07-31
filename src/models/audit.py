"""QueryAudit and MetadataReview models."""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import (
    Base,
    pk_column,
    created_at_column,
    optional_string_column,
    required_string_column,
)


class QueryAudit(Base):
    """An audit record of a user query."""

    __tablename__ = "query_audit"

    id: Mapped[str] = pk_column()
    user_id: Mapped[str | None] = optional_string_column()
    user_email: Mapped[str | None] = optional_string_column()
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = optional_string_column()
    response_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    response_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]


class MetadataReview(Base):
    """Admin review and correction of extracted metadata."""

    __tablename__ = "metadata_reviews"

    id: Mapped[str] = pk_column()
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = required_string_column()
    field_name: Mapped[str] = required_string_column()
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = optional_string_column()
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]
