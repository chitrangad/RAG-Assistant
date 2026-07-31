"""Embedding provider — generates vector embeddings for text chunks."""

from abc import ABC, abstractmethod

from src.logging_config import get_logger

logger = get_logger(__name__)


class EmbeddingProvider(ABC):
    """Abstract interface for generating embeddings."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...

    @abstractmethod
    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        ...


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Embedding provider using a local sentence-transformers model.

    Default: all-MiniLM-L6-v2 (384 dimensions, ~80MB, CPU-friendly).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._warmed_up = False

    def _load_model(self):
        """Lazy-load the model on first use."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("loading_embedding_model", model=self.model_name)
            self._model = SentenceTransformer(self.model_name)
            logger.info(
                "embedding_model_loaded",
                model=self.model_name,
                dimension=self._model.get_sentence_embedding_dimension(),
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        if not texts:
            return []
        self._load_model()
        # sentence-transformers encode is synchronous; run in default executor
        import asyncio
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: self._model.encode(texts, show_progress_bar=False).tolist()
        )
        return embeddings

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        results = await self.embed([text])
        return results[0]

    @property
    def dimension(self) -> int:
        self._load_model()
        return self._model.get_sentence_embedding_dimension()

    def warm_up(self):
        """Pre-load the model (call at startup)."""
        self._load_model()
        self._warmed_up = True
