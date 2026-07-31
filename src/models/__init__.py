"""SQLAlchemy models package — all models are imported here for Alembic discovery."""

from src.models.base import Base
from src.models.project import Project, ProjectAlias
from src.models.document import Document, ProjectDocument, DocumentChunk
from src.models.requirement import Requirement, ProjectRequirement
from src.models.change_request import ChangeRequest, ProjectChangeRequest
from src.models.artifact import Artifact, ProjectArtifact
from src.models.evidence import EvidenceLink
from src.models.source import DataSource, SourceDocument
from src.models.ingestion import IngestionRun
from src.models.audit import QueryAudit, MetadataReview

__all__ = [
    "Base",
    "Project",
    "ProjectAlias",
    "Document",
    "ProjectDocument",
    "DocumentChunk",
    "Requirement",
    "ProjectRequirement",
    "ChangeRequest",
    "ProjectChangeRequest",
    "Artifact",
    "ProjectArtifact",
    "EvidenceLink",
    "DataSource",
    "SourceDocument",
    "IngestionRun",
    "QueryAudit",
    "MetadataReview",
]
