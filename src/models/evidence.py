"""EvidenceLink model — connects claims to source document chunks."""

from datetime import datetime
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import (
    Base,
    pk_column,
    created_at_column,
    optional_string_column,
    required_string_column,
)


class EvidenceLink(Base):
    """A link between a claim/answer and its supporting source chunk."""

    __tablename__ = "evidence_links"

    id: Mapped[str] = pk_column()
    claim_type: Mapped[str] = mapped_column(String(50), nullable=False)
    claim_id: Mapped[str] = required_string_column()
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False
    )
    citation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = created_at_column()  # type: ignore[assignment]

    document: Mapped["Document"] = relationship()
    chunk: Mapped["DocumentChunk"] = relationship()
