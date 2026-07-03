"""FAISS vector index over local fastembed embeddings.

Embeddings run locally (no API key, no per-token cost) via fastembed's ONNX
runtime. The embedding model is loaded once per process and shared; the
FAISS index itself is built per review, since every review indexes a
different repository.

Similarity is cosine (inner product over L2-normalized vectors), which is
what the BGE embedding models are trained for.
"""

import threading

import faiss
import numpy as np
from fastembed import TextEmbedding

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.chunk_service import Chunk

logger = get_logger("services.vector")


class VectorIndexError(Exception):
    """The vector index could not be built or queried."""


class VectorService:
    """A per-review vector index: build once with `build()`, then `search()`."""

    _embedder: TextEmbedding | None = None
    _embedder_lock = threading.Lock()

    def __init__(self) -> None:
        self._index: faiss.IndexFlatIP | None = None
        self._chunks: list[Chunk] = []

    # ------------------------------------------------------------------ #
    # Embedding model (shared, lazy)
    # ------------------------------------------------------------------ #
    @classmethod
    def _get_embedder(cls) -> TextEmbedding:
        """Load the embedding model once per process (thread-safe)."""
        if cls._embedder is None:
            with cls._embedder_lock:
                if cls._embedder is None:
                    model_name = get_settings().embedding_model
                    logger.info("Loading embedding model %s ...", model_name)
                    cls._embedder = TextEmbedding(model_name=model_name)
                    logger.info("Embedding model ready")
        return cls._embedder

    @classmethod
    def _embed(cls, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        embedder = cls._get_embedder()
        batch_size = get_settings().embedding_batch_size

        # BGE models are trained with distinct query/passage encodings;
        # fastembed exposes them where supported.
        if is_query and hasattr(embedder, "query_embed"):
            vectors = list(embedder.query_embed(texts))
        elif not is_query and hasattr(embedder, "passage_embed"):
            vectors = list(embedder.passage_embed(texts, batch_size=batch_size))
        else:
            vectors = list(embedder.embed(texts, batch_size=batch_size))

        matrix = np.asarray(vectors, dtype="float32")
        faiss.normalize_L2(matrix)  # cosine similarity via inner product
        return matrix

    # ------------------------------------------------------------------ #
    # Index lifecycle
    # ------------------------------------------------------------------ #
    def build(self, chunks: list[Chunk]) -> None:
        """Embed all chunks and build the FAISS index."""
        if not chunks:
            raise VectorIndexError("Cannot build an index from zero chunks.")

        embeddings = self._embed([c.text for c in chunks])
        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)

        self._index = index
        self._chunks = list(chunks)
        logger.info(
            "Indexed %d chunks (dim=%d)", index.ntotal, embeddings.shape[1]
        )

    def search(self, query: str, k: int | None = None) -> list[Chunk]:
        """Return the `k` chunks most relevant to `query`, best first."""
        if self._index is None:
            raise VectorIndexError("search() called before build().")

        k = k or get_settings().chunks_per_agent
        k = min(k, self._index.ntotal)
        if k <= 0:
            return []

        query_vector = self._embed([query], is_query=True)
        _scores, indices = self._index.search(query_vector, k)
        return [self._chunks[i] for i in indices[0] if i >= 0]

    @property
    def size(self) -> int:
        return self._index.ntotal if self._index is not None else 0
