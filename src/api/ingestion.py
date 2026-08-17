"""Ingestion API endpoints — source management, upload, and ingestion triggers.

All heavy imports (embedder, orchestrator, and ingestion module types that trigger
ChromaDB) are lazy to avoid loading sentence-transformers/ChromaDB at import time.
They're only loaded when an ingestion endpoint is actually called.
"""

from fastapi import APIRouter, File, UploadFile, Form, HTTPException

from src.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])

# Lazy singleton holders (initialized on first use)
_embedder = None
_orchestrator = None


def _get_embedder():
    """Lazy-load the SentenceTransformer embedder."""
    global _embedder
    if _embedder is None:
        from src.ingestion.embedder import SentenceTransformerEmbedder

        _embedder = SentenceTransformerEmbedder()
        _embedder.warm_up()
    return _embedder


def _get_orchestrator():
    """Lazy-load the IngestionOrchestrator."""
    global _orchestrator
    if _orchestrator is None:
        from src.ingestion.orchestrator import IngestionOrchestrator

        _orchestrator = IngestionOrchestrator(embedder=_get_embedder())
    return _orchestrator


@router.post("/local-folder")
async def ingest_local_folder(
    folder_path: str = Form(...),
    recursive: bool = Form(default=True),
):
    """Ingest all supported documents from a local folder.

    Scans the folder recursively by default, discovers .pdf/.docx/.md/.txt
    files, extracts text and metadata, chunks, embeds, and indexes them.
    """
    from src.ingestion.local_folder import LocalFolderConnector

    connector = LocalFolderConnector(folder_path=folder_path, recursive=recursive)

    if not await connector.validate():
        raise HTTPException(
            status_code=400,
            detail=f"Folder not found or not accessible: {folder_path}",
        )

    orchestrator = _get_orchestrator()
    result = await orchestrator.ingest_from_connector(connector, source_id="local")
    return result


@router.post("/upload")
async def ingest_upload(
    file: UploadFile = File(...),
):
    """Upload and ingest a single document file.

    Accepts .pdf, .docx, .epub, .md, or .txt files. The file is staged,
    extracted, chunked, embedded, and indexed.
    """
    # Validate file type
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if f".{ext}" not in {".pdf", ".docx", ".epub", ".md", ".txt"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{ext}. Supported: .pdf, .docx, .epub, .md, .txt",
        )

    content = await file.read()
    from src.ingestion.upload import UploadedFile

    uploaded = UploadedFile(filename=file.filename, content=content)

    orchestrator = _get_orchestrator()
    result = await orchestrator.ingest_uploaded_file(uploaded)
    return result


@router.get("/stats")
async def ingestion_stats():
    """Return statistics about the vector store."""
    orchestrator = _get_orchestrator()
    chunk_count = orchestrator.chroma_store.count()
    return {
        "chunks_indexed": chunk_count,
    }
