"""Document upload connector — handles files uploaded via the API."""

import os
import tempfile
from datetime import datetime
from pathlib import Path

from src.ingestion.connector import SourceConnector, DocumentCandidate
from src.logging_config import get_logger

logger = get_logger(__name__)


class UploadedFile:
    """Represents a file uploaded via the API."""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.content = content
        self.ext = Path(filename).suffix.lower()

    @property
    def size(self) -> int:
        return len(self.content)


class DocumentUploadConnector:
    """Processes individually uploaded files (not a persistent source connector).

    Unlike folder/share connectors, this handles one-off uploads. It uses a
    temporary staging directory to persist files for the ingestion pipeline.
    """

    def __init__(self, upload_dir: str | Path):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def stage_upload(self, uploaded: UploadedFile) -> DocumentCandidate:
        """Save an uploaded file to staging and return a candidate."""
        # Generate a unique filename to avoid collisions
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_name = f"{timestamp}_{uploaded.filename}"
        dest_path = self.upload_dir / safe_name

        with open(dest_path, "wb") as f:
            f.write(uploaded.content)

        candidate = DocumentCandidate(
            file_name=uploaded.filename,
            file_path=str(dest_path),
            file_type=uploaded.ext,
            file_size_bytes=uploaded.size,
            last_modified=datetime.utcnow(),
            source_metadata={
                "source_type": "upload",
                "original_filename": uploaded.filename,
            },
        )
        logger.info("upload_staged", filename=uploaded.filename, path=str(dest_path))
        return candidate

    async def read_content(self, file_path: str) -> bytes:
        """Read the raw content of a staged file."""
        with open(file_path, "rb") as f:
            return f.read()

    def cleanup(self, file_path: str) -> None:
        """Remove a staged file after ingestion."""
        try:
            os.remove(file_path)
            logger.info("staged_file_cleaned", path=file_path)
        except OSError as e:
            logger.warning("staged_file_cleanup_failed", path=file_path, error=str(e))
