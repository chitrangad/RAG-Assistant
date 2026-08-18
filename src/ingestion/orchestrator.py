"""Ingestion orchestrator — coordinates the full ingestion pipeline."""

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src import database as database_mod
from src.ingestion.connector import DocumentCandidate, SourceConnector
from src.ingestion.extractor import DocumentExtractor
from src.ingestion.metadata import MetadataExtractor
from src.ingestion.chunker import DocumentChunker, TextChunk
from src.ingestion.embedder import EmbeddingProvider
from src.ingestion.chroma_store import ChromaVectorStore
from src.ingestion.registry import DocumentRegistry
from src.ingestion.upload import DocumentUploadConnector, UploadedFile
from src.models.ingestion import IngestionRun
from src.logging_config import get_logger

logger = get_logger(__name__)


class IngestionOrchestrator:
    """Coordinates the full ingestion pipeline: discover → extract → chunk → embed → index."""

    def __init__(
        self,
        embedder: EmbeddingProvider,
        chroma_store: ChromaVectorStore | None = None,
    ):
        self.extractor = DocumentExtractor()
        self.metadata_extractor = MetadataExtractor()
        self.chunker = DocumentChunker(
            chunk_size=settings.chunk_size,  # type: ignore[attr-defined]
            chunk_overlap=settings.chunk_overlap,  # type: ignore[attr-defined]
        )
        self.embedder = embedder
        self.chroma_store = chroma_store or ChromaVectorStore()
        self.upload_handler = DocumentUploadConnector(settings.upload_dir)

    async def ingest_from_connector(
        self,
        connector: SourceConnector,
        source_id: str | None = None,
        run_id: str | None = None,
    ) -> dict:
        """Discover and ingest all documents from a source connector.

        If ``run_id`` is provided, progress is written to that existing
        ingestion run (committed per document so clients can poll live
        progress). Otherwise a fresh run is created.

        Returns a summary dict with counts and any errors.
        """
        if not await connector.validate():
            raise ValueError(f"Source connector validation failed: {connector}")

        candidates = await connector.discover_documents()
        logger.info(
            "ingestion_discovery_complete",
            source_id=source_id,
            document_count=len(candidates),
        )

        processed = 0
        indexed = 0
        errors: list[str] = []

        async with database_mod.async_session_factory() as db:
            registry = DocumentRegistry(db)

            # Load the pre-created run (for live progress) or create a new one
            run = None
            if run_id:
                result = await db.execute(
                    select(IngestionRun).where(IngestionRun.id == run_id)
                )
                run = result.scalar_one_or_none()
            if run is None:
                run = await registry.create_ingestion_run(source_id)
            run.documents_discovered = len(candidates)
            await db.commit()  # make the running run visible to pollers

            try:
                for candidate in candidates:
                    try:
                        # Use a savepoint per document so a single failure
                        # doesn't poison the outer transaction or detach the
                        # ingestion run object.
                        async with db.begin_nested():
                            await self._process_document(
                                connector=connector,
                                candidate=candidate,
                                registry=registry,
                                source_id=source_id,
                            )
                        processed += 1
                        indexed += 1
                    except Exception as e:
                        error_msg = f"{candidate.file_name}: {e}"
                        errors.append(error_msg)
                        logger.error(
                            "document_ingestion_failed",
                            file=candidate.file_name,
                            error=str(e),
                        )
                        # Savepoint auto-rolled back on exception; no explicit
                        # rollback needed — the outer session stays clean.

                    # Live progress update, committed so clients can poll
                    run.documents_processed = processed
                    run.documents_indexed = indexed
                    await db.commit()

                await registry.complete_ingestion_run(
                    run=run,
                    discovered=len(candidates),
                    processed=processed,
                    indexed=indexed,
                    errors="\n".join(errors) if errors else None,
                )
                await db.commit()

            except Exception as e:
                # Mark the run failed so it never lingers in "running"
                try:
                    await db.rollback()
                    run.status = "failed"
                    run.errors = str(e)[:2000]
                    await db.commit()
                except Exception:
                    pass
                raise

        return {
            "status": "completed" if not errors else "completed_with_errors",
            "documents_discovered": len(candidates),
            "documents_processed": processed,
            "documents_indexed": indexed,
            "errors": errors,
        }

    async def ingest_uploaded_file(
        self,
        uploaded_file: UploadedFile,
    ) -> dict:
        """Ingest a single uploaded file.

        Returns a summary dict.
        """
        candidate = await self.upload_handler.stage_upload(uploaded_file)

        async with database_mod.async_session_factory() as db:
            registry = DocumentRegistry(db)
            run = await registry.create_ingestion_run()

            try:
                await self._process_document(
                    connector=None,
                    candidate=candidate,
                    registry=registry,
                    source_id=None,
                    file_content=uploaded_file.content,
                )
                await db.commit()
                await registry.complete_ingestion_run(
                    run=run,
                    discovered=1,
                    processed=1,
                    indexed=1,
                )
                await db.commit()
            except Exception as e:
                await db.rollback()
                raise
            finally:
                self.upload_handler.cleanup(str(candidate.file_path))

        return {
            "status": "completed",
            "documents_discovered": 1,
            "documents_processed": 1,
            "documents_indexed": 1,
            "errors": [],
            "document_name": uploaded_file.filename,
        }

    async def _process_document(
        self,
        connector: SourceConnector | None,
        candidate: DocumentCandidate,
        registry: DocumentRegistry,
        source_id: str | None = None,
        file_content: bytes | None = None,
    ) -> None:
        """Process a single document through the full pipeline."""
        # 1. Read content
        if file_content is not None:
            content = file_content
        elif connector is not None:
            content = await connector.read_content(candidate.file_path)
        else:
            raise ValueError("Either connector or file_content must be provided")

        # 2. Extract text
        raw_text = self.extractor.extract(content, candidate.file_type)
        if not raw_text.strip():
            logger.warning("empty_document", file=candidate.file_name)
            return

        # 3. Hash content so re-scans can detect unchanged/changed documents.
        content_hash = hashlib.sha256(content).hexdigest()

        # 4. Extract metadata
        metadata = self.metadata_extractor.extract(raw_text)

        # 5. Register document in catalog (dedupes by path + content hash so an
        # incremental re-scan merges instead of duplicating).
        doc, action = await registry.register_document(
            candidate, source_id, content_hash
        )
        if action == "unchanged":
            logger.info("document_unchanged", doc_id=doc.id, file=candidate.file_name)
            return

        # If the document changed, remove its old chunks first so re-indexing
        # replaces them instead of appending duplicates.
        if action == "updated":
            self.chroma_store.delete_by_document(doc.id)
            await registry.delete_chunks(doc.id)

        # 6. Link to projects based on metadata
        for project_name in metadata.get("project_names", []):
            project = await registry.find_or_create_project(project_name)
            await registry.link_document_to_project(project.id, doc.id)

            for req_id in metadata.get("requirement_ids", []):
                await registry.link_requirement(project.id, req_id, doc.id)

            for cr_number in metadata.get("change_request_ids", []):
                await registry.link_change_request(project.id, cr_number, doc.id)

        # 6. Chunk
        chunks = self.chunker.chunk(raw_text)
        if not chunks:
            return

        # 7. Embed
        chunk_texts = [c.content for c in chunks]
        embeddings = await self.embedder.embed(chunk_texts)

        # 8. Index in ChromaDB
        chroma_ids = [str(uuid.uuid4()) for _ in chunks]
        self.chroma_store.add_chunks(
            ids=chroma_ids,
            embeddings=embeddings,
            documents=chunk_texts,
            metadatas=[
                {
                    "document_id": doc.id,
                    "source_id": source_id or "upload",
                    "file_name": candidate.file_name,
                    "file_type": candidate.file_type,
                    "chunk_index": c.chunk_index,
                    "project_names": ",".join(metadata.get("project_names", [])),
                    "requirement_ids": ",".join(metadata.get("requirement_ids", [])),
                    "cr_numbers": ",".join(metadata.get("change_request_ids", [])),
                }
                for c in chunks
            ],
        )

        # 9. Save chunks to catalog
        await registry.save_chunks(doc.id, chunks, chroma_ids)

        logger.info(
            "document_ingested",
            file=candidate.file_name,
            chunks=len(chunks),
            requirements=len(metadata.get("requirement_ids", [])),
        )
