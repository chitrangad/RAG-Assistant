"""Source connector abstract base class and shared types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def normalize_extensions(extensions: list[str] | None) -> set[str]:
    """Normalise extension strings to a set of lowercase, dotless names.

    Accepts messy input (``["epub", ".Docx", "  md "]``) and returns a clean
    set (``{"epub", "docx", "md"}``). Used to filter file types during scans.
    """
    if not extensions:
        return set()
    result: set[str] = set()
    for ext in extensions:
        name = (ext or "").strip().lstrip(".").lower()
        if name:
            result.add(name)
    return result


@dataclass
class DocumentCandidate:
    """A document discovered by a connector, before ingestion."""

    file_name: str
    file_path: str
    file_type: str  # "pdf", "docx", "md", "txt"
    file_size_bytes: int
    last_modified: datetime
    source_metadata: dict[str, Any] = field(default_factory=dict)


class SourceConnector(ABC):
    """Abstract interface for a document source connector.

    Each connector discovers documents from a source (local folder, upload,
    network share, SharePoint, etc.) and provides access to their content.
    """

    @abstractmethod
    async def validate(self) -> bool:
        """Validate that the source is accessible and configured correctly."""
        ...

    @abstractmethod
    async def discover_documents(self) -> list[DocumentCandidate]:
        """Discover all documents available from this source."""
        ...

    @abstractmethod
    async def read_content(self, document_id: str) -> bytes:
        """Read the raw content of a document by its identifier."""
        ...
