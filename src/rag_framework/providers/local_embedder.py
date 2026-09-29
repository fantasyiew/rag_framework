"""Lazy local inference, serialized in a worker thread; no fallback model."""

import asyncio
import threading

from rag_framework.contracts.providers import Embedder
from rag_framework.core.vectors import EmbeddingError, validate_vectors


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, settings):
        if not settings.embedding_model:
            raise ValueError('Local embeddings require embedding_model')
        self.config = settings
        self.model = None
        self.lock = threading.Lock()

    def _encode(self, texts, prefix):
        # A threading lock remains held even when the awaiting coroutine is cancelled.
        with self.lock:
            try:
                if self.model is None:
                    from sentence_transformers import SentenceTransformer

                    model = SentenceTransformer(
                        self.config.embedding_model,
                        device=self.config.embedding_device,
                        revision=self.config.embedding_model_revision,
                        local_files_only=self.config.embedding_local_files_only,
                        trust_remote_code=False,
                    )
                    if model.get_sentence_embedding_dimension() != self.config.embedding_dimensions:
                        raise EmbeddingError('Local model dimension differs from configuration')
                    self.model = model
                vectors = self.model.encode(
                    [prefix + value for value in texts],
                    batch_size=self.config.embedding_batch_size,
                    normalize_embeddings=self.config.embedding_normalize,
                    show_progress_bar=False, convert_to_numpy=True,
                    prompt='',  # Use explicit prefixes, not a model's implicit default prompt.
                ).tolist()
                return validate_vectors(vectors, len(texts), self.config.embedding_dimensions)
            except (ImportError, OSError, RuntimeError, ValueError, TypeError, AttributeError):
                raise EmbeddingError(
                    'Local embedding failed; check optional dependency, cached model, device and dimensions'
                ) from None

    async def embed_documents(self, texts):
        if not texts:
            return []
        return await asyncio.to_thread(self._encode, texts, self.config.embedding_document_prefix)

    async def embed_query(self, text):
        return (await asyncio.to_thread(self._encode, [text], self.config.embedding_query_prefix))[0]
