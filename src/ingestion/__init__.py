"""Ingestion package — source discovery, extraction, metadata, chunking, embedding, indexing."""

from src.ingestion.connector import SourceConnector, DocumentCandidate
from src.ingestion.extractor import DocumentExtractor
from src.ingestion.metadata import MetadataExtractor
from src.ingestion.chunker import DocumentChunker, TextChunk
from src.ingestion.embedder import EmbeddingProvider, SentenceTransformerEmbedder
from src.ingestion.chroma_store import ChromaVectorStore
from src.ingestion.registry import DocumentRegistry
from src.ingestion.orchestrator import IngestionOrchestrator
from src.ingestion.local_folder import LocalFolderConnector
from src.ingestion.upload import DocumentUploadConnector, UploadedFile

__all__ = [
    "SourceConnector",
    "DocumentCandidate",
    "DocumentExtractor",
    "MetadataExtractor",
    "DocumentChunker",
    "TextChunk",
    "EmbeddingProvider",
    "SentenceTransformerEmbedder",
    "ChromaVectorStore",
    "DocumentRegistry",
    "IngestionOrchestrator",
    "LocalFolderConnector",
    "DocumentUploadConnector",
    "UploadedFile",
]
