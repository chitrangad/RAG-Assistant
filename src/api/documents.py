"""Document serving — stream an ingested file back to the browser.

This is how clickable citations work for *network shares*: the browser cannot
open a server-side path like ``/run/user/1001/gvfs/smb-share:...``, so we
proxy the file through the backend (which has the share mounted) and return it
over HTTP. Works identically for local folders and uploads.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# ``file_type`` is stored with a leading dot (".txt", ".pdf", …).
_CONTENT_TYPES = {
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """Serve the original file for an ingested document (inline when viewable)."""
    from sqlalchemy import select

    from src.database import async_session_factory
    from src.models.document import Document

    async with async_session_factory() as db:
        doc = await db.get(Document, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        file_path = doc.file_path
        file_name = doc.file_name
        file_type = doc.file_type or ""

    if not file_path:
        raise HTTPException(status_code=404, detail="Document has no stored file path")

    path = Path(file_path)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Document file is not accessible (its source may be unmounted).",
        )

    # Normalise: some ingestion paths store "txt" while others store ".txt".
    ft = file_type if file_type.startswith(".") else f".{file_type}"
    media_type = _CONTENT_TYPES.get(ft, "application/octet-stream")
    disposition = "inline" if ft in (".txt", ".md", ".pdf") else "attachment"

    return FileResponse(
        path,
        media_type=media_type,
        filename=file_name,
        content_disposition_type=disposition,
    )
