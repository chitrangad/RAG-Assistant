"""Chat / Query API — semantic search over indexed document chunks."""

import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.ingestion.chroma_store import ChromaVectorStore
from src.llm.factory import get_llm
from src.llm.settings import load_settings
from src.llm.prompts import (
    ENUMERATION_SYSTEM_PROMPT,
    INSUFFICIENT_EVIDENCE_ANSWER,
    SYSTEM_PROMPT,
    build_enumeration_prompt,
    build_grounding_prompt,
)
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
    document_id: str = ""
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


class RepoDocument(BaseModel):
    """A single indexed document, for the catalog-listing intent.

    ``document_id`` is the key for ``GET /api/documents/{id}`` (open/download).
    """

    document_id: str
    file_name: str
    folder: str
    file_type: str
    file_size_bytes: int | None = None
    source: str = ""


class QueryResponse(BaseModel):
    question: str
    intent: str = Field(default="semantic", description="semantic | listing")
    results: list[EvidenceChunk]
    folders: list[FolderInfo] = Field(default_factory=list)
    documents: list[RepoDocument] = Field(
        default_factory=list,
        description="Flat document list for catalog-listing intent",
    )
    total_chunks_searched: int
    answer: str | None = Field(
        default=None, description="Natural-language answer synthesized from evidence"
    )
    citations: list[str] = Field(
        default_factory=list, description="Source document names cited in the answer"
    )
    insufficient_evidence: bool = Field(
        default=False,
        description="True when evidence was too weak; answer is the FR-009 fallback",
    )


# ── Catalog listing (intent detection for "list all documents") ──────

# Phrases that signal a request to enumerate the document catalog.
_LISTING_PATTERNS = [
    r"list\s+(?:all\s+|the\s+|a\s+|any\s+|project\s+|available\s+|indexed\s+)*(?:documents?|files?|docs)",
    r"(?:show|display|enumerate)\s+(?:me\s+)?(?:all\s+|the\s+|available\s+)*(?:documents?|files?)",
    r"(?:list|show)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:documents?|files?)\s+in\s+(?:the\s+)?(?:repo|repository)",
    r"what\s+(?:documents?|files?)\s+(?:do\s+we\s+have|are\s+(?:there|available|indexed|in\s+the\s+repo)|exist)",
    r"which\s+(?:documents?|files?)\s+(?:do\s+we\s+have|are\s+(?:there|available|indexed|in\s+the\s+repo)|exist)",
    r"all\s+(?:the\s+)?(?:documents?|files?)\s+in\s+(?:the\s+)?(?:repository|index|system|catalog|repo)",
    r"(?:catalog|inventory)\s+of\s+(?:all\s+|the\s+)?(?:documents?|files?)",
    r"(?:show|list)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:documents?|files?)\s+(?:available|present)",
]

# Words that make the question a targeted lookup rather than a listing.
_NON_LISTING_WORDS = re.compile(
    r"\b(about|related|mention|contain|pertaining|regarding|for|with)\b"
)

# ── Count / enumeration intent (exact count & complete lists) ───────────

# These questions need ALL matching items, not just the top few chunks, so the
# answer can be exact instead of a vague "several books like ...".
_ENUMERATION_PATTERNS = [
    r"\bhow many\b",
    r"\bcount\b",
    r"\bnumber of\b",
    r"\btotal\b",
    r"\benumerate\b",
    r"\blist\s+(?:all|every|each)\b",
    r"\b(?:all|every|each)\s+(?:the\s+)?(?:books?|reports?|docs?|documents?|files?|items?|projects?|requirements?)\b",
]

# How many chunks to retrieve for enumeration questions (Chroma returns all of
# them ranked; we compact down to one snippet per document afterwards).
_ENUMERATION_RETRIEVAL_K = 200
# Max distinct documents fed to the model (keeps context under local n_ctx).
_ENUMERATION_MAX_EVIDENCE = 25
# Max chars of snippet per document in enumeration evidence.
_ENUMERATION_SNIPPET_CHARS = 400


def _is_enumeration_query(question: str) -> bool:
    """True if the question asks for an exact count or a complete list."""
    q = question.lower().strip()
    return any(re.search(p, q) for p in _ENUMERATION_PATTERNS)


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


async def _list_repo_documents() -> list[RepoDocument]:
    """Enumerate every indexed document, each with an open/download id.

    Sourced from the SQLite catalog (the authoritative index) rather than a
    filesystem walk: it is fast, works regardless of share mount state, and
    every entry already has a ``document_id`` for ``GET /api/documents/{id}``.
    """
    from src.database import async_session_factory
    from src.models.document import Document
    from src.models.source import DataSource, SourceDocument
    from sqlalchemy import select

    async with async_session_factory() as db:
        doc_rows = await db.execute(
            select(
                Document.id,
                Document.file_name,
                Document.file_path,
                Document.file_type,
                Document.file_size_bytes,
            )
        )
        documents = doc_rows.all()

        link_rows = await db.execute(
            select(SourceDocument.document_id, DataSource.name).join(
                DataSource, DataSource.id == SourceDocument.source_id
            )
        )
        sources: dict[str, set[str]] = {}
        for doc_id, source_name in link_rows:
            sources.setdefault(doc_id, set()).add(source_name)

    docs = [
        RepoDocument(
            document_id=doc_id,
            file_name=file_name or "",
            folder=_clean_folder_path(file_path or ""),
            file_type=file_type or "",
            file_size_bytes=size,
            source=", ".join(sorted(sources.get(doc_id, ()))),
        )
        for doc_id, file_name, file_path, file_type, size in documents
    ]
    docs.sort(key=lambda d: (d.folder.lower(), d.file_name.lower()))
    return docs


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
        documents = await _list_repo_documents()
        logger.info(
            "query_listing",
            question=request.question[:80],
            folders=len(folders),
            documents=len(documents),
        )
        return QueryResponse(
            question=request.question,
            intent="listing",
            results=[],
            folders=folders,
            documents=documents,
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

    # Count / enumeration questions retrieve far beyond the default top-k so
    # the evidence contains every matching item and the answer can be exact
    # ("5 books: A, B, ...") instead of vague.
    enumeration = _is_enumeration_query(request.question)
    n_results = min(chunk_count, _ENUMERATION_RETRIEVAL_K) if enumeration else request.top_k

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
            n_results=n_results,
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
                document_id=doc_id,
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

    # Answer synthesis (best-effort) — synthesize a natural-language answer
    # from the top evidence using the configured LLM provider. Degrades to
    # evidence-only when the provider is unavailable.
    answer: str | None = None
    citations: list[str] = []
    insufficient_evidence = False

    top_score = results[0].relevance_score if results else 0.0
    llm_settings = load_settings()

    if not results or top_score < llm_settings.min_relevance_score:
        insufficient_evidence = True
        answer = INSUFFICIENT_EVIDENCE_ANSWER
    else:
        try:
            provider = get_llm()
            if enumeration:
                # Compact broad evidence to one snippet per document (title =
                # file name) so the model can count distinct items exactly
                # without overflowing the local model's context window.
                best_by_doc: dict[str, EvidenceChunk] = {}
                for r in results:
                    existing = best_by_doc.get(r.document_id)
                    if existing is None or r.relevance_score > existing.relevance_score:
                        best_by_doc[r.document_id] = r
                docs = sorted(
                    best_by_doc.values(), key=lambda r: -r.relevance_score
                )[:_ENUMERATION_MAX_EVIDENCE]
                evidence = [
                    {
                        "document_name": d.document_name,
                        "file_path": d.file_path,
                        "chunk_content": d.chunk_content[:_ENUMERATION_SNIPPET_CHARS],
                    }
                    for d in docs
                ]
                prompt = build_enumeration_prompt(request.question, evidence)
                system_prompt = ENUMERATION_SYSTEM_PROMPT
                # Lists are longer than the default 2-3 sentence answers.
                max_tokens = max(llm_settings.max_tokens, 512)
            else:
                evidence = [
                    {
                        "document_name": r.document_name,
                        "file_path": r.file_path,
                        "chunk_content": r.chunk_content,
                    }
                    for r in results
                ]
                prompt = build_grounding_prompt(request.question, evidence)
                system_prompt = SYSTEM_PROMPT
                max_tokens = llm_settings.max_tokens
            answer = await provider.generate(
                prompt,
                system=system_prompt,
                max_tokens=max_tokens,
                temperature=llm_settings.temperature,
            )
            citations = [e["document_name"] for e in evidence]
            logger.info(
                "answer_synthesized",
                question=request.question[:80],
                provider=llm_settings.provider,
                citations=len(citations),
                enumeration=enumeration,
            )
        except Exception as e:
            # Provider unavailable (model missing, no API key, offline, etc.).
            # Return evidence-only rather than failing the request.
            logger.error("answer_synthesis_failed", error=str(e))
            answer = None

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
        answer=answer,
        citations=citations,
        insufficient_evidence=insufficient_evidence,
    )
