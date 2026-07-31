"""Chat / Query API — semantic search over indexed document chunks."""

import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.ingestion.chroma_store import ChromaVectorStore
from src.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# ── Lazy singleton holders ──────────────────────────────────────────
_embedder = None
_chroma_store = None


def _get_embedder():
    """Lazy-load the SentenceTransformer embedder (shared with ingestion)."""
    global _embedder
    if _embedder is None:
        from src.ingestion.embedder import SentenceTransformerEmbedder

        _embedder = SentenceTransformerEmbedder()
        _embedder.warm_up()
    return _embedder


def _get_chroma_store():
    """Lazy-load the ChromaDB vector store."""
    global _chroma_store
    if _chroma_store is None:
        _chroma_store = ChromaVectorStore()
    return _chroma_store


# ── Pydantic schemas ────────────────────────────────────────────────


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural language question")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of results")


class EvidenceChunk(BaseModel):
    document_name: str
    file_type: str
    file_path: str = ""
    chunk_content: str
    relevance_score: float
    project_names: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    cr_numbers: list[str] = Field(default_factory=list)


class FolderInfo(BaseModel):
    """A folder (project) derived from document file paths, with a doc count."""

    folder: str
    document_count: int
    sources: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    question: str
    intent: str = Field(default="semantic", description="semantic | listing")
    results: list[EvidenceChunk]
    folders: list[FolderInfo] = Field(default_factory=list)
    total_chunks_searched: int


# ── Catalog listing (intent detection for "list all documents") ──────

# Phrases that signal a request to enumerate the document catalog.
_LISTING_PATTERNS = [
    r"list\s+(?:all\s+|the\s+|a\s+|any\s+|project\s+|available\s+|indexed\s+)*(?:documents?|files?|docs)",
    r"(?:show|display|enumerate)\s+(?:me\s+)?(?:all\s+|the\s+)*(?:documents?|files?)",
    r"what\s+(?:documents?|files?)\s+(?:do\s+we\s+have|are\s+(?:there|available|indexed)|exist)",
    r"which\s+(?:documents?|files?)\s+(?:do\s+we\s+have|are\s+(?:there|available|indexed)|exist)",
    r"all\s+(?:the\s+)?(?:documents?|files?)\s+in\s+(?:the\s+)?(?:repository|index|system|catalog)",
    r"(?:catalog|inventory)\s+of\s+(?:all\s+|the\s+)?(?:documents?|files?)",
]

# Words that make the question a targeted lookup rather than a listing.
_NON_LISTING_WORDS = re.compile(
    r"\b(about|related|mention|contain|pertaining|regarding|for|with)\b"
)


def _is_listing_query(question: str) -> bool:
    """True if the question asks to enumerate the document catalog."""
    q = question.lower().strip()
    if not q or _NON_LISTING_WORDS.search(q):
        return False
    return any(re.search(p, q) for p in _LISTING_PATTERNS)


def _clean_folder_path(file_path: str) -> str:
    """Turn a document's directory into a readable folder/project name."""
    folder = os.path.dirname(file_path)
    folder = re.sub(r"^/run/user/\d+/gvfs/", "", folder)
    m = re.match(r"^smb-share:server=[^,]+,[^/]*/(.*)$", folder)
    if m:
        folder = m.group(1)
    folder = re.sub(r"^/home/[^/]+/project_rag/", "", folder)
    folder = folder.rstrip("/")
    return folder or "/"


async def _list_document_folders() -> list[FolderInfo]:
    """Group all indexed documents by their folder (project) — no vector store."""
    from src.database import async_session_factory
    from src.models.document import Document
    from src.models.source import DataSource, SourceDocument
    from sqlalchemy import select

    grouped: dict[str, dict] = {}
    async with async_session_factory() as db:
        rows = await db.execute(
            select(Document.file_path, DataSource.name)
            .outerjoin(SourceDocument, SourceDocument.document_id == Document.id)
            .outerjoin(DataSource, DataSource.id == SourceDocument.source_id)
        )
        for file_path, source_name in rows:
            folder = _clean_folder_path(file_path or "")
            entry = grouped.setdefault(folder, {"count": 0, "sources": set()})
            entry["count"] += 1
            if source_name:
                entry["sources"].add(source_name)

    return [
        FolderInfo(
            folder=folder,
            document_count=info["count"],
            sources=sorted(info["sources"]),
        )
        for folder, info in sorted(
            grouped.items(), key=lambda kv: (-kv[1]["count"], kv[0].lower())
        )
    ]


# ── Endpoints ───────────────────────────────────────────────────────


@router.post("/query", response_model=QueryResponse)
async def query_chat(request: QueryRequest):
    """Answer a question from indexed documents.

    Catalog-listing questions ("list all documents") return the full folder
    inventory from SQLite. Everything else runs semantic search over ChromaDB
    and returns ranked evidence with citations.
    """
    # Catalog listing intent — no vector store needed
    if _is_listing_query(request.question):
        folders = await _list_document_folders()
        logger.info(
            "query_listing",
            question=request.question[:80],
            folders=len(folders),
        )
        return QueryResponse(
            question=request.question,
            intent="listing",
            results=[],
            folders=folders,
            total_chunks_searched=0,
        )

    embedder = _get_embedder()
    chroma_store = _get_chroma_store()

    # Check there's something to search
    chunk_count = chroma_store.count()
    if chunk_count == 0:
        raise HTTPException(
            status_code=404,
            detail="No documents indexed. Upload or ingest documents first.",
        )

    # Embed the question
    try:
        query_embedding = await embedder.embed_single(request.question)
    except Exception as e:
        logger.error("query_embedding_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to embed query.") from e

    # Search ChromaDB
    try:
        raw = chroma_store.query(
            query_embedding=query_embedding,
            n_results=request.top_k,
        )
    except Exception as e:
        logger.error("chroma_query_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Vector search failed.") from e

    # Collect document IDs to look up file paths from SQLite
    doc_ids: set[str] = set()
    results_raw: list[dict] = []
    if raw.get("ids") and raw["ids"][0]:
        for i in range(len(raw["ids"][0])):
            meta = (raw.get("metadatas", [[]])[0] or [{}])[i] if i < len(raw.get("metadatas", [[]])[0]) else {}
            doc = (raw.get("documents", [[]])[0] or [""])[i] if i < len(raw.get("documents", [[]])[0]) else ""
            distance = (raw.get("distances", [[]])[0] or [1.0])[i] if i < len(raw.get("distances", [[]])[0]) else 1.0
            doc_id = meta.get("document_id", "")
            if doc_id:
                doc_ids.add(doc_id)
            results_raw.append((meta, doc, distance, doc_id))

    # Look up file paths from the document catalog
    file_paths: dict[str, str] = {}
    if doc_ids:
        from src.database import async_session_factory
        from src.models.document import Document
        from sqlalchemy import select

        async with async_session_factory() as db:
            result = await db.execute(
                select(Document.id, Document.file_path).where(Document.id.in_(list(doc_ids)))
            )
            for row in result:
                file_paths[row[0]] = row[1] or ""

    # Build response
    results: list[EvidenceChunk] = []
    for meta, doc, distance, doc_id in results_raw:
        score = round(max(0.0, min(1.0, 1.0 - distance)), 4)
        fp = file_paths.get(doc_id, "")
        results.append(
            EvidenceChunk(
                document_name=meta.get("file_name", "unknown"),
                file_type=meta.get("file_type", ""),
                file_path=fp,
                chunk_content=doc,
                relevance_score=score,
                project_names=(
                    meta.get("project_names", "").split(",")
                    if meta.get("project_names")
                    else []
                ),
                requirement_ids=(
                    meta.get("requirement_ids", "").split(",")
                    if meta.get("requirement_ids")
                    else []
                ),
                cr_numbers=(
                    meta.get("cr_numbers", "").split(",")
                    if meta.get("cr_numbers")
                    else []
                ),
            )
        )

    logger.info(
        "query_complete",
        question=request.question[:80],
        results=len(results),
        top_score=results[0].relevance_score if results else None,
    )

    return QueryResponse(
        question=request.question,
        intent="semantic",
        results=results,
        total_chunks_searched=chunk_count,
    )
