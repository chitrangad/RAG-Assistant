"""ChromaDB vector store wrapper — semantic search accelerator."""

import uuid
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)


class ChromaVectorStore:
    """Wraps ChromaDB for storing and searching document chunk embeddings.

    Design rule from spec:
        SQLite = source of truth
        ChromaDB = semantic search accelerator
    """

    COLLECTION_NAME = "document_chunks"

    def __init__(self):
        self._client: chromadb.PersistentClient | None = None
        self._collection: chromadb.Collection | None = None

    @property
    def client(self) -> chromadb.PersistentClient:
        if self._client is None:
            persist_dir = Path(settings.chroma_persist_dir)
            persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            logger.info("chroma_client_initialized", path=str(persist_dir))
        return self._client

    @property
    def collection(self) -> chromadb.Collection:
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def add_chunks(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Add document chunks with embeddings to the vector store."""
        if not ids:
            return
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info("chroma_chunks_added", count=len(ids))

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query the vector store for similar chunks.

        Returns ChromaDB query result with ids, distances, documents, metadatas.
        """
        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    def delete_by_document(self, document_id: str) -> None:
        """Delete all chunks belonging to a document."""
        self.collection.delete(where={"document_id": document_id})
        logger.info("chroma_document_deleted", document_id=document_id)

    def delete_by_source(self, source_id: str) -> None:
        """Delete all chunks belonging to a source."""
        self.collection.delete(where={"source_id": source_id})
        logger.info("chroma_source_deleted", source_id=source_id)

    def count(self) -> int:
        """Return the number of chunks in the collection."""
        return self.collection.count()
