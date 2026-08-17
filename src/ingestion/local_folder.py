"""Local folder connector — discovers and reads documents from a directory."""

import os
from datetime import datetime
from pathlib import Path

from src.ingestion.connector import SourceConnector, DocumentCandidate
from src.logging_config import get_logger

logger = get_logger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".epub", ".md", ".txt"}


class LocalFolderConnector(SourceConnector):
    """Discovers documents from a local directory."""

    def __init__(self, folder_path: str, recursive: bool = True):
        self.folder_path = Path(folder_path).expanduser().absolute()
        self.recursive = recursive

    async def validate(self) -> bool:
        """Check that the folder exists and is readable."""
        try:
            return self.folder_path.exists() and self.folder_path.is_dir()
        except Exception:
            return False

    async def discover_documents(self) -> list[DocumentCandidate]:
        """Scan the folder for supported document types."""
        candidates: list[DocumentCandidate] = []
        pattern = "**/*" if self.recursive else "*"

        for file_path in self.folder_path.glob(pattern):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            stat = file_path.stat()
            candidate = DocumentCandidate(
                file_name=file_path.name,
                file_path=str(file_path),
                file_type=ext,
                file_size_bytes=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime),
                source_metadata={
                    "source_type": "local_folder",
                    "root_path": str(self.folder_path),
                    "relative_path": str(file_path.relative_to(self.folder_path)),
                },
            )
            candidates.append(candidate)

        logger.info(
            "local_folder_scan_complete",
            folder=str(self.folder_path),
            file_count=len(candidates),
        )
        return candidates

    async def read_content(self, file_path: str) -> bytes:
        """Read the raw bytes of a file."""
        with open(file_path, "rb") as f:
            return f.read()
