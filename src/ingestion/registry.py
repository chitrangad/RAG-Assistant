"""Document registry — database operations for ingested documents."""

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import now_utc

from src.ingestion.connector import DocumentCandidate
from src.ingestion.chunker import TextChunk
from src.models.document import Document, DocumentChunk, ProjectDocument
from src.models.source import SourceDocument
from src.models.ingestion import IngestionRun
from src.models.requirement import Requirement, ProjectRequirement
from src.models.change_request import ChangeRequest, ProjectChangeRequest
from src.models.project import Project
from src.logging_config import get_logger

logger = get_logger(__name__)


class DocumentRegistry:
    """Handles all database operations for the ingestion pipeline."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def register_document(
        self, candidate: DocumentCandidate, source_id: str | None = None
    ) -> Document:
        """Register a new document or return existing one (by path + hash)."""
        # Check for existing document by path
        result = await self.db.execute(
            select(Document).where(Document.file_path == candidate.file_path)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        doc = Document(
            file_name=candidate.file_name,
            file_path=candidate.file_path,
            file_type=candidate.file_type,
            file_size_bytes=candidate.file_size_bytes,
            last_modified=candidate.last_modified,
        )
        self.db.add(doc)
        await self.db.flush()

        # Link to source if provided
        if source_id:
            source_doc = SourceDocument(
                source_id=source_id,
                document_id=doc.id,
            )
            self.db.add(source_doc)

        logger.info("document_registered", doc_id=doc.id, file_name=doc.file_name)
        return doc

    async def save_chunks(
        self,
        document_id: str,
        chunks: list[TextChunk],
        chroma_ids: list[str],
    ) -> list[DocumentChunk]:
        """Persist document chunks with their ChromaDB IDs."""
        db_chunks = []
        for chunk, chroma_id in zip(chunks, chroma_ids):
            db_chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
                chroma_id=chroma_id,
            )
            self.db.add(db_chunk)
            db_chunks.append(db_chunk)

        await self.db.flush()
        logger.info(
            "chunks_saved",
            document_id=document_id,
            chunk_count=len(db_chunks),
        )
        return db_chunks

    async def find_or_create_project(self, name: str) -> Project:
        """Find an existing project by name, or create a new one."""
        result = await self.db.execute(
            select(Project).where(Project.name == name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        project = Project(name=name)
        self.db.add(project)
        await self.db.flush()
        logger.info("project_created", project_id=project.id, name=name)
        return project

    async def link_requirement(
        self,
        project_id: str,
        requirement_id: str,
        document_id: str,
        title: str | None = None,
    ) -> Requirement:
        """Create or find a requirement and link it to a project."""
        result = await self.db.execute(
            select(Requirement).where(Requirement.requirement_id == requirement_id)
        )
        req = result.scalar_one_or_none()
        if req is None:
            req = Requirement(
                requirement_id=requirement_id,
                title=title,
                source_document_id=document_id,
            )
            self.db.add(req)
            await self.db.flush()

        # Link to project if not already linked
        link_result = await self.db.execute(
            select(ProjectRequirement).where(
                ProjectRequirement.project_id == project_id,
                ProjectRequirement.requirement_id == req.id,
            )
        )
        if link_result.scalar_one_or_none() is None:
            link = ProjectRequirement(
                project_id=project_id,
                requirement_id=req.id,
            )
            self.db.add(link)

        return req

    async def link_change_request(
        self,
        project_id: str,
        cr_number: str,
        document_id: str,
        title: str | None = None,
    ) -> ChangeRequest:
        """Create or find a change request and link it to a project."""
        result = await self.db.execute(
            select(ChangeRequest).where(ChangeRequest.cr_number == cr_number)
        )
        cr = result.scalar_one_or_none()
        if cr is None:
            cr = ChangeRequest(
                cr_number=cr_number,
                title=title,
                source_document_id=document_id,
            )
            self.db.add(cr)
            await self.db.flush()

        link_result = await self.db.execute(
            select(ProjectChangeRequest).where(
                ProjectChangeRequest.project_id == project_id,
                ProjectChangeRequest.change_request_id == cr.id,
            )
        )
        if link_result.scalar_one_or_none() is None:
            link = ProjectChangeRequest(
                project_id=project_id,
                change_request_id=cr.id,
            )
            self.db.add(link)

        return cr

    async def link_document_to_project(
        self, project_id: str, document_id: str
    ) -> None:
        """Link a document to a project if not already linked."""
        result = await self.db.execute(
            select(ProjectDocument).where(
                ProjectDocument.project_id == project_id,
                ProjectDocument.document_id == document_id,
            )
        )
        if result.scalar_one_or_none() is None:
            link = ProjectDocument(
                project_id=project_id,
                document_id=document_id,
            )
            self.db.add(link)

    async def create_ingestion_run(
        self, source_id: str | None = None
    ) -> IngestionRun:
        """Create a new ingestion run tracking record."""
        run = IngestionRun(
            source_id=source_id or "manual",
            status="running",
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def complete_ingestion_run(
        self,
        run: IngestionRun,
        discovered: int,
        processed: int,
        indexed: int,
        errors: str | None = None,
    ) -> None:
        """Mark an ingestion run as completed."""
        run.status = "completed" if not errors else "completed_with_errors"
        run.completed_at = now_utc()
        run.documents_discovered = discovered
        run.documents_processed = processed
        run.documents_indexed = indexed
        run.errors = errors
