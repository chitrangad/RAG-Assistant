"""Admin API — source management, ingestion triggers, health monitoring."""

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session_factory
from src.models.source import DataSource
from src.models.ingestion import IngestionRun
from src.models.base import now_utc
from src.logging_config import get_logger
from src.auth import require_admin
from src.llm.settings import LLMSettings, load_settings, save_settings
from src.llm.factory import reset_llm_cache
from src.llm.downloader import DEFAULT_MODEL_URL, get_downloader

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

# ── Lazy singletons (loaded on first use to avoid heavy imports) ──
_embedder = None
_orchestrator = None
_chroma_store = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from src.ingestion.embedder import SentenceTransformerEmbedder

        _embedder = SentenceTransformerEmbedder()
        _embedder.warm_up()
    return _embedder


def _get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from src.ingestion.orchestrator import IngestionOrchestrator

        _orchestrator = IngestionOrchestrator(embedder=_get_embedder())
    return _orchestrator


def _get_chroma():
    global _chroma_store
    if _chroma_store is None:
        from src.ingestion.chroma_store import ChromaVectorStore

        _chroma_store = ChromaVectorStore()
    return _chroma_store


# ── Pydantic schemas ────────────────────────────────────────────────


class SourceCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Display name for this source")
    source_type: str = Field(
        ...,
        pattern="^(network_share|local_folder|sharepoint|upload)$",
        description="Type of source connector",
    )
    path: str = Field(
        "",
        description="Filesystem path (for network_share or local_folder)",
    )
    scan_mode: str = Field(
        default="incremental",
        pattern="^(full|incremental)$",
    )
    owner_email: str | None = None
    network_user: str | None = Field(None, description="Network username for authenticated shares")
    network_pass: str | None = Field(None, description="Network password for authenticated shares")
    network_domain: str | None = Field(None, description="Network domain (optional, for Windows/SMB auth)")


class SourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    path: str | None = None
    enabled: bool
    scan_mode: str
    last_indexed_at: datetime | None = None
    last_status: str | None = None
    owner_email: str | None = None
    network_user: str | None = None
    has_credentials: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceDocumentResponse(BaseModel):
    id: str
    file_name: str
    file_type: str
    file_path: str | None = None
    file_size_bytes: int | None = None
    last_modified: datetime | None = None
    created_at: datetime


class IngestionRunResponse(BaseModel):
    id: str
    source_id: str
    started_at: datetime
    completed_at: datetime | None = None
    documents_discovered: int
    documents_processed: int
    documents_indexed: int
    status: str
    errors: str | None = None


class AdminHealthResponse(BaseModel):
    status: str
    database: str
    chromadb: str
    total_sources: int
    total_documents: int
    total_chunks: int
    total_ingestion_runs: int


class LLMSettingsResponse(BaseModel):
    provider: str
    model_path: str
    n_ctx: int
    n_threads: int
    temperature: float
    max_tokens: int
    no_think: bool
    base_url: str
    model: str
    min_relevance_score: float
    has_api_key: bool = False
    api_key_last4: str = ""
    local_model_available: bool = False
    default_model_url: str = ""


class LLMSettingsUpdate(BaseModel):
    provider: str | None = Field(None, pattern="^(local|external)$")
    model_path: str | None = None
    n_ctx: int | None = Field(None, ge=256, le=32768)
    n_threads: int | None = Field(None, ge=1, le=64)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=64, le=4096)
    no_think: bool | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    min_relevance_score: float | None = Field(None, ge=0.0, le=1.0)


class LLMTestResponse(BaseModel):
    success: bool
    detail: str
    latency_ms: int = 0


class ReindexRequest(BaseModel):
    source_id: str | None = Field(None, description="Source ID to reindex, or None for all")


class SourceUpdate(BaseModel):
    """All fields optional — only provided fields are updated."""
    name: str | None = Field(None, min_length=1)
    path: str | None = None
    scan_mode: str | None = Field(None, pattern="^(full|incremental)$")
    owner_email: str | None = None
    network_user: str | None = None
    network_pass: str | None = None
    network_domain: str | None = None


# ── Helper ───────────────────────────────────────────────────────────


async def _ds_to_response(ds: DataSource) -> SourceResponse:
    cd = ds.connection_details or {}
    return SourceResponse(
        id=ds.id,
        name=ds.name,
        source_type=ds.source_type,
        path=cd.get("path"),
        enabled=ds.enabled,
        scan_mode=ds.scan_mode,
        last_indexed_at=ds.last_indexed_at,
        last_status=ds.last_status,
        owner_email=ds.owner_email,
        network_user=cd.get("network_user"),
        has_credentials=bool(cd.get("network_user") and cd.get("network_pass")),
        created_at=ds.created_at,
    )


# ── Source CRUD ──────────────────────────────────────────────────────


@router.get("/sources", response_model=list[SourceResponse])
async def list_sources():
    """List all registered data sources."""
    async with async_session_factory() as db:
        result = await db.execute(select(DataSource).order_by(DataSource.created_at))
        sources = result.scalars().all()
        return [await _ds_to_response(s) for s in sources]


@router.post("/sources", response_model=SourceResponse, status_code=201)
async def create_source(body: SourceCreate):
    """Register a new data source."""
    async with async_session_factory() as db:
        existing = await db.execute(
            select(DataSource).where(DataSource.name == body.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Source '{body.name}' already exists")

        cd = {"path": body.path} if body.path else {}
        if body.network_user:
            cd["network_user"] = body.network_user
        if body.network_pass:
            cd["network_pass"] = body.network_pass
        if body.network_domain:
            cd["network_domain"] = body.network_domain

        ds = DataSource(
            name=body.name,
            source_type=body.source_type,
            connection_details=cd if cd else None,
            scan_mode=body.scan_mode,
            owner_email=body.owner_email,
            created_by="admin",
        )
        db.add(ds)
        await db.commit()
        await db.refresh(ds)
        return await _ds_to_response(ds)


@router.patch("/sources/{source_id}", response_model=SourceResponse)
async def update_source(source_id: str, body: SourceUpdate):
    """Update an existing data source. Only provided fields are changed."""
    async with async_session_factory() as db:
        result = await db.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="Source not found")

        # Copy the dict so SQLAlchemy detects the change on assignment.
        # Mutating the ORM's JSON column in place (then reassigning the same
        # object) is silently ignored, so the path never persisted.
        cd = dict(ds.connection_details or {})

        if body.name is not None:
            ds.name = body.name
        if body.path is not None:
            cd["path"] = body.path
        if body.scan_mode is not None:
            ds.scan_mode = body.scan_mode
        if body.owner_email is not None:
            ds.owner_email = body.owner_email
        if body.network_user is not None:
            cd["network_user"] = body.network_user
        if body.network_pass is not None:
            cd["network_pass"] = body.network_pass
        if body.network_domain is not None:
            cd["network_domain"] = body.network_domain

        ds.connection_details = cd if cd else None
        await db.commit()
        await db.refresh(ds)
        return await _ds_to_response(ds)


@router.get("/sources/{source_id}/documents", response_model=list[SourceDocumentResponse])
async def list_source_documents(source_id: str):
    """List all files ingested for a single source."""
    from src.models.source import SourceDocument
    from src.models.document import Document

    async with async_session_factory() as db:
        result = await db.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="Source not found")

        rows = await db.execute(
            select(Document)
            .join(SourceDocument, SourceDocument.document_id == Document.id)
            .where(SourceDocument.source_id == source_id)
            .order_by(Document.file_name)
        )
        docs = rows.scalars().all()

    return [
        SourceDocumentResponse(
            id=d.id,
            file_name=d.file_name,
            file_type=d.file_type,
            file_path=d.file_path,
            file_size_bytes=d.file_size_bytes,
            last_modified=d.last_modified,
            created_at=d.created_at,
        )
        for d in docs
    ]


@router.get("/sources/{source_id}", response_model=SourceResponse)
async def get_source(source_id: str):
    """Get a single data source by ID."""
    async with async_session_factory() as db:
        result = await db.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return await _ds_to_response(ds)


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str):
    """Delete a data source and its ingestion history."""
    async with async_session_factory() as db:
        result = await db.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="Source not found")
        await db.delete(ds)
        await db.commit()
    return {"detail": f"Source '{ds.name}' deleted"}


@router.patch("/sources/{source_id}/toggle")
async def toggle_source(source_id: str):
    """Enable or disable a data source."""
    async with async_session_factory() as db:
        result = await db.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="Source not found")
        ds.enabled = not ds.enabled
        await db.commit()
    return {"detail": f"Source '{ds.name}' {'enabled' if ds.enabled else 'disabled'}", "enabled": ds.enabled}


# ── Test connection ──────────────────────────────────────────────────


class TestConnectionResponse(BaseModel):
    success: bool
    detail: str
    files_found: int = 0


@router.post("/sources/{source_id}/test", response_model=TestConnectionResponse)
async def test_connection(source_id: str):
    """Test connectivity to a source without ingesting anything."""
    async with async_session_factory() as db:
        result = await db.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="Source not found")

        cd = ds.connection_details or {}
        path = cd.get("path")
        if not path:
            raise HTTPException(status_code=400, detail="Source has no path configured")

        from src.ingestion.network_share import NetworkShareConnector

        connector = NetworkShareConnector(
            share_path=path,
            recursive=True,
            username=cd.get("network_user"),
            password=cd.get("network_pass"),
            domain=cd.get("network_domain"),
        )

        # Validate connectivity
        if not await connector.validate():
            return TestConnectionResponse(
                success=False,
                detail=f"Cannot access: {path}. Check the path and credentials.",
            )

        # Try discovering files (just count them, don't ingest)
        try:
            docs = await connector.discover_documents()
            return TestConnectionResponse(
                success=True,
                detail=f"Connected. Found {len(docs)} document(s).",
                files_found=len(docs),
            )
        except Exception as e:
            return TestConnectionResponse(
                success=False,
                detail=f"Connected but listing failed: {e}",
            )


# ── Ingestion triggers ───────────────────────────────────────────────


# Background scan tasks are held here so the event loop doesn't GC them.
_background_tasks: set[asyncio.Task] = set()


async def _run_scan_background(
    source_id: str,
    run_id: str,
    path: str,
    net_user: str | None,
    net_pass: str | None,
    net_domain: str | None,
) -> None:
    """Run ingestion for a source in the background, updating live progress."""
    try:
        from src.ingestion.network_share import NetworkShareConnector

        connector = NetworkShareConnector(
            share_path=path,
            recursive=True,
            username=net_user,
            password=net_pass,
            domain=net_domain,
        )

        orchestrator = _get_orchestrator()
        result = await orchestrator.ingest_from_connector(
            connector, source_id=source_id, run_id=run_id
        )

        # Update source status
        async with async_session_factory() as db:
            ds = (
                await db.execute(select(DataSource).where(DataSource.id == source_id))
            ).scalar_one_or_none()
            if ds:
                ds.last_indexed_at = now_utc()
                ds.last_status = result["status"]
                await db.commit()
        logger.info(
            "background_scan_complete",
            source_id=source_id,
            run_id=run_id,
            status=result["status"],
        )
    except Exception as e:
        logger.error("background_scan_failed", source_id=source_id, run_id=run_id, error=str(e))
        # Mark the run as failed so polling clients see a terminal state
        try:
            async with async_session_factory() as db:
                run = await db.get(IngestionRun, run_id)
                if run:
                    run.status = "failed"
                    run.errors = str(e)[:2000]
                    await db.commit()
        except Exception:
            pass


@router.post("/sources/{source_id}/scan", status_code=202)
async def scan_source(source_id: str):
    """Trigger background ingestion for a source.

    Validates the source synchronously (fast fail), creates the ingestion run
    record, then starts discovery + ingestion as a background task. The client
    polls ``GET /api/admin/runs/{run_id}`` to show live progress.
    """
    async with async_session_factory() as db:
        result = await db.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="Source not found")

        if ds.source_type not in ("network_share", "local_folder"):
            raise HTTPException(
                status_code=400,
                detail=f"Scan not supported for source type: {ds.source_type}",
            )

        cd = ds.connection_details or {}
        path = cd.get("path")
        if not path:
            raise HTTPException(status_code=400, detail="Source has no path configured")
        net_user = cd.get("network_user")
        net_pass = cd.get("network_pass")
        net_domain = cd.get("network_domain")

        # Quick connectivity check (fast fail for bad paths)
        from src.ingestion.network_share import NetworkShareConnector

        connector = NetworkShareConnector(
            share_path=path,
            recursive=True,
            username=net_user,
            password=net_pass,
            domain=net_domain,
        )
        if not await connector.validate():
            ds.last_status = "error: path not accessible"
            await db.commit()
            raise HTTPException(
                status_code=400,
                detail=f"Path not accessible: {path}. Ensure the network drive is mounted.",
            )

        # Create the run row now so clients can track progress immediately
        from src.ingestion.registry import DocumentRegistry

        registry = DocumentRegistry(db)
        run = await registry.create_ingestion_run(source_id)
        await db.commit()
        run_id = run.id

    task = asyncio.create_task(
        _run_scan_background(source_id, run_id, path, net_user, net_pass, net_domain)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {
        "status": "started",
        "run_id": run_id,
        "source_id": source_id,
        "detail": "Ingestion started in background. Poll /api/admin/runs/{run_id} for progress.",
    }


# ── Run history ──────────────────────────────────────────────────────


@router.get("/sources/{source_id}/runs", response_model=list[IngestionRunResponse])
async def list_runs(source_id: str, limit: int = Query(default=10, le=50)):
    """List recent ingestion runs for a source."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(IngestionRun)
            .where(IngestionRun.source_id == source_id)
            .order_by(desc(IngestionRun.started_at))
            .limit(limit)
        )
        runs = result.scalars().all()
    return [
        IngestionRunResponse(
            id=r.id,
            source_id=r.source_id,
            started_at=r.started_at,
            completed_at=r.completed_at,
            documents_discovered=r.documents_discovered,
            documents_processed=r.documents_processed,
            documents_indexed=r.documents_indexed,
            status=r.status,
            errors=r.errors,
        )
        for r in runs
    ]


@router.get("/runs", response_model=list[IngestionRunResponse])
async def list_all_runs(limit: int = Query(default=20, le=100)):
    """List recent ingestion runs across all sources."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(IngestionRun)
            .order_by(desc(IngestionRun.started_at))
            .limit(limit)
        )
        runs = result.scalars().all()
    return [
        IngestionRunResponse(
            id=r.id,
            source_id=r.source_id,
            started_at=r.started_at,
            completed_at=r.completed_at,
            documents_discovered=r.documents_discovered,
            documents_processed=r.documents_processed,
            documents_indexed=r.documents_indexed,
            status=r.status,
            errors=r.errors,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=IngestionRunResponse)
async def get_run(run_id: str):
    """Get a single ingestion run by ID — used to poll live scan progress."""
    async with async_session_factory() as db:
        run = await db.get(IngestionRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
    return IngestionRunResponse(
        id=run.id,
        source_id=run.source_id,
        started_at=run.started_at,
        completed_at=run.completed_at,
        documents_discovered=run.documents_discovered,
        documents_processed=run.documents_processed,
        documents_indexed=run.documents_indexed,
        status=run.status,
        errors=run.errors,
    )


# ── Health ───────────────────────────────────────────────────────────


@router.get("/health", response_model=AdminHealthResponse)
async def admin_health():
    """Extended health check with database and ChromaDB status."""
    db_status = "ok"
    chroma_status = "ok"
    total_sources = 0
    total_docs = 0
    total_chunks = 0
    total_runs = 0

    # Check database
    try:
        async with async_session_factory() as db:
            r = await db.execute(select(func.count()).select_from(DataSource))
            total_sources = r.scalar() or 0

            from src.models.document import Document, DocumentChunk

            r = await db.execute(select(func.count()).select_from(Document))
            total_docs = r.scalar() or 0

            r = await db.execute(select(func.count()).select_from(DocumentChunk))
            total_chunks = r.scalar() or 0

            r = await db.execute(select(func.count()).select_from(IngestionRun))
            total_runs = r.scalar() or 0
    except Exception as e:
        db_status = f"error: {e}"

    # Check ChromaDB
    try:
        chroma = _get_chroma()
        chroma.count()
    except Exception as e:
        chroma_status = f"error: {e}"

    return AdminHealthResponse(
        status="healthy" if db_status == "ok" and chroma_status == "ok" else "degraded",
        database=db_status,
        chromadb=chroma_status,
        total_sources=total_sources,
        total_documents=total_docs,
        total_chunks=total_chunks,
        total_ingestion_runs=total_runs,
    )


# ── Data cleanup ─────────────────────────────────────────────────────


@router.delete("/data")
async def clear_all_data():
    """Delete ALL ingested data: ChromaDB chunks, documents, runs.

    Keeps data source configurations intact.
    """
    from src.models.document import Document, DocumentChunk, ProjectDocument
    from src.models.requirement import Requirement, ProjectRequirement
    from src.models.change_request import ChangeRequest, ProjectChangeRequest

    chroma_before = 0
    docs_before = 0

    # 1. Wipe ChromaDB
    try:
        chroma = _get_chroma()
        chroma_before = chroma.count()
        # Delete all entries from the collection
        chroma.collection.delete(where={})
        logger.info("clear_all_chroma_deleted", count=chroma_before)
    except Exception as e:
        logger.error("clear_all_chroma_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"ChromaDB cleanup failed: {e}")

    # 2. Wipe SQLite (order matters for FK constraints)
    async with async_session_factory() as db:
        r = await db.execute(select(func.count()).select_from(Document))
        docs_before = r.scalar() or 0

        tables = [
            ProjectChangeRequest,
            ProjectRequirement,
            ProjectDocument,
            DocumentChunk,
            ChangeRequest,
            Requirement,
            IngestionRun,
            Document,
        ]
        for table in tables:
            await db.execute(table.__table__.delete())

        await db.commit()

    return {
        "detail": "All ingested data cleared",
        "chroma_chunks_deleted": chroma_before,
        "documents_deleted": docs_before,
    }


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a specific ingestion run and all data associated with its source."""
    from src.models.document import Document, DocumentChunk, ProjectDocument
    from src.models.requirement import Requirement, ProjectRequirement
    from src.models.change_request import ChangeRequest, ProjectChangeRequest

    async with async_session_factory() as db:
        # Find the run
        result = await db.execute(
            select(IngestionRun).where(IngestionRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")

        source_id = run.source_id
        run_status = run.status

        # Find all documents linked to this source
        from src.models.source import SourceDocument
        doc_result = await db.execute(
            select(SourceDocument.document_id).where(SourceDocument.source_id == source_id)
        )
        doc_ids = [row[0] for row in doc_result.all()]

        # Delete chunks from ChromaDB for this source
        try:
            chroma = _get_chroma()
            chroma.delete_by_source(source_id)
            logger.info("run_delete_chroma", run_id=run_id, source_id=source_id)
        except Exception as e:
            logger.error("run_delete_chroma_failed", error=str(e))

        # Delete from SQLite
        if doc_ids:
            for table in [DocumentChunk, ProjectDocument, ProjectRequirement, ProjectChangeRequest]:
                await db.execute(table.__table__.delete().where(
                    table.__table__.c.document_id.in_(doc_ids)
                    if hasattr(table, 'document_id') else
                    table.__table__.c.id.in_(doc_ids)
                ))

            # Delete linked requirements and CRs that only belong to these docs
            await db.execute(Requirement.__table__.delete().where(
                Requirement.source_document_id.in_(doc_ids)
            ))
            await db.execute(ChangeRequest.__table__.delete().where(
                ChangeRequest.source_document_id.in_(doc_ids)
            ))

            # Delete documents
            await db.execute(Document.__table__.delete().where(
                Document.id.in_(doc_ids)
            ))

        # Delete the source-document links
        from src.models.source import SourceDocument
        await db.execute(SourceDocument.__table__.delete().where(
            SourceDocument.source_id == source_id
        ))

        # Delete the run itself
        await db.delete(run)
        await db.commit()

    return {
        "detail": f"Run '{run_id}' and its data deleted",
        "source_id": source_id,
        "documents_deleted": len(doc_ids),
        "run_status": run_status,
    }


# ── LLM / answer-engine settings ───────────────────────────────────────


def _llm_to_response(s: LLMSettings) -> LLMSettingsResponse:
    """Build a response, masking the API key and flagging model availability."""
    model_path = Path(s.model_path)
    return LLMSettingsResponse(
        provider=s.provider,
        model_path=s.model_path,
        n_ctx=s.n_ctx,
        n_threads=s.n_threads,
        temperature=s.temperature,
        max_tokens=s.max_tokens,
        no_think=s.no_think,
        base_url=s.base_url,
        model=s.model,
        min_relevance_score=s.min_relevance_score,
        has_api_key=bool(s.api_key),
        api_key_last4=s.api_key[-4:] if s.api_key else "",
        local_model_available=model_path.exists(),
        default_model_url=DEFAULT_MODEL_URL,
    )


@router.get("/llm-settings", response_model=LLMSettingsResponse)
async def get_llm_settings():
    """Return the current answer-engine settings (API key masked)."""
    return _llm_to_response(load_settings())


@router.put("/llm-settings", response_model=LLMSettingsResponse)
async def update_llm_settings(body: LLMSettingsUpdate):
    """Update answer-engine settings. An empty/omitted ``api_key`` keeps the existing one."""
    current = load_settings()

    if body.provider is not None:
        current.provider = body.provider
    if body.model_path is not None:
        current.model_path = body.model_path
    if body.n_ctx is not None:
        current.n_ctx = body.n_ctx
    if body.n_threads is not None:
        current.n_threads = body.n_threads
    if body.temperature is not None:
        current.temperature = body.temperature
    if body.max_tokens is not None:
        current.max_tokens = body.max_tokens
    if body.no_think is not None:
        current.no_think = body.no_think
    if body.base_url is not None:
        current.base_url = body.base_url
    if body.api_key:  # empty string = keep existing (avoids wiping on unrelated edits)
        current.api_key = body.api_key
    if body.model is not None:
        current.model = body.model
    if body.min_relevance_score is not None:
        current.min_relevance_score = body.min_relevance_score

    save_settings(current)
    reset_llm_cache()
    logger.info("llm_settings_updated", provider=current.provider)
    return _llm_to_response(current)


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm():
    """Send a trivial prompt to the configured provider to verify it works.

    For the local provider the first call loads the model (can take a while).
    """
    import time

    from src.llm.factory import get_llm

    s = load_settings()
    start = time.perf_counter()
    try:
        provider = get_llm()
        await provider.generate(
            "Reply with exactly the word: OK",
            system="You are a test harness.",
            max_tokens=8,
            temperature=0.0,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return LLMTestResponse(
            success=True,
            detail=f"Provider responded successfully ({s.provider})",
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.error("llm_test_failed", provider=s.provider, error=str(e))
        return LLMTestResponse(success=False, detail=str(e), latency_ms=latency_ms)


class ModelDownloadRequest(BaseModel):
    url: str | None = Field(None, description="GGUF model URL to download")
    model_path: str | None = Field(None, description="Destination path (defaults to configured model path)")


@router.post("/llm/download-model")
async def start_model_download(body: ModelDownloadRequest | None = None):
    """Download an answer LLM (GGUF) to the configured model path.

    Optionally pass ``url`` (the model file URL) and ``model_path`` (where to
    save it); defaults to the Qwen3-1.7B model and the configured model path.
    Runs in a background thread; poll ``GET /llm/download-model`` for progress.
    """
    s = load_settings()
    url = (body.url or DEFAULT_MODEL_URL) if body else DEFAULT_MODEL_URL
    target = (body.model_path or s.model_path) if body else s.model_path
    state = get_downloader().start(target, url=url)
    if state["status"] == "downloading":
        logger.info("model_download_started", path=state["path"])
    return {**state, "url": url}


@router.get("/llm/download-model")
async def get_model_download_status():
    """Poll the model download progress."""
    return get_downloader().state()


# ── Quick scan ───────────────────────────────────────────────────────


@router.post("/scan")
async def quick_scan(
    path: str = Form(..., description="Filesystem path to scan"),
    source_name: str = Form(default="Quick Scan", description="Label for this scan"),
    recursive: bool = Form(default=True),
):
    """Quick one-shot scan of any path without creating a persistent source.

    Useful for testing or one-off ingestion from a network drive.
    """
    from src.ingestion.network_share import NetworkShareConnector

    connector = NetworkShareConnector(share_path=path, recursive=recursive)

    if not await connector.validate():
        raise HTTPException(
            status_code=400,
            detail=f"Path not accessible: {path}",
        )

    orchestrator = _get_orchestrator()
    import uuid as _uuid
    result = await orchestrator.ingest_from_connector(connector, source_id=f"quick_scan_{_uuid.uuid4().hex[:8]}")
    result["source_name"] = source_name
    return result
