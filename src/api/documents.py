"""Document serving — stream an ingested file back to the browser.

This is how clickable citations work for *network shares*: the browser cannot
open a server-side path like ``/run/user/1000/gvfs/smb-share:...`` or a virtual
``smb://host/share/...`` URL, so we proxy the file through the backend and
return it over HTTP. Works for local folders, uploads, mounted shares, and
remote SMB shares (fetched via smbclient, no mount required).
"""

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

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

    # Normalise: some ingestion paths store "txt" while others store ".txt".
    ft = file_type if file_type.startswith(".") else f".{file_type}"
    media_type = _CONTENT_TYPES.get(ft, "application/octet-stream")
    disposition = "inline" if ft in (".txt", ".md", ".pdf") else "attachment"

    # SMB-mode documents store a virtual `smb://host/share/...` path that the
    # local filesystem can't see — fetch the bytes through the same smbclient
    # path the connector uses, with the source's stored credentials.
    if file_path.startswith("smb://"):
        data = await _read_smb_document(doc_id, file_path)
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": _content_disposition(disposition, file_name)},
        )

    path = Path(file_path)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Document file is not accessible (its source may be unmounted).",
        )

    return FileResponse(
        path,
        media_type=media_type,
        filename=file_name,
        content_disposition_type=disposition,
    )


def _content_disposition(disposition: str, file_name: str) -> str:
    """Build a Content-Disposition header, UTF-8 encoded like FileResponse does."""
    return f"{disposition}; filename*=UTF-8''{quote(file_name)}"


async def _read_smb_document(doc_id: str, file_path: str) -> bytes:
    """Fetch a document's bytes from its SMB source via smbclient.

    Looks up the owning data source for the source's connection details
    (credentials), then reuses ``NetworkShareConnector.read_content`` which
    handles the smbclient ``get`` (run off the event loop).
    """
    from sqlalchemy import select

    from src.database import async_session_factory
    from src.ingestion.network_share import NetworkShareConnector
    from src.models.source import DataSource, SourceDocument

    async with async_session_factory() as db:
        link = (
            await db.execute(
                select(SourceDocument).where(SourceDocument.document_id == doc_id)
            )
        ).scalars().first()
        if link is None:
            raise HTTPException(
                status_code=404,
                detail="Document file is not accessible: no source found for this document.",
            )
        ds = await db.get(DataSource, link.source_id)
        cd = (ds.connection_details or {}) if ds else {}
        path = cd.get("path")
        if not path:
            raise HTTPException(
                status_code=404,
                detail="Document file is not accessible: its source has no path configured.",
            )

    connector = NetworkShareConnector(
        share_path=path,
        username=cd.get("network_user"),
        password=cd.get("network_pass"),
        domain=cd.get("network_domain"),
    )
    try:
        return await connector.read_content(file_path)
    except Exception as e:  # noqa: BLE001 - surface any smbclient failure
        logger.warning("smb_document_read_failed", doc_id=doc_id, error=str(e))
        raise HTTPException(
            status_code=404,
            detail=f"Document file is not accessible over SMB: {e}",
        ) from e