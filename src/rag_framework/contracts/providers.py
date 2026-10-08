"""Ports used by the pipeline. Provider implementations depend on these, never vice versa."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from rag_framework.core.models import (
    Chunk,
    Document,
    Query,
    RetrievalPlan,
    RetrievalTrace,
    RetrievedChunk,
)


class Chunker(ABC):
    @property
    def parameters(self) -> dict[str, object]:
        return {}

    @abstractmethod
    def split(self, document: Document) -> list[Chunk]: ...


class Fusion(ABC):
    @property
    def parameters(self) -> dict[str, object]:
        return {}

    @abstractmethod
    def fuse(
        self, result_sets: dict[str, list[RetrievedChunk]], *, top_k: int
    ) -> list[RetrievedChunk]: ...


class Embedder(ABC):
    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...


class VectorStore(ABC):
    async def iter_chunks(self, *, page_size: int = 256) -> AsyncIterator[Chunk]:
        """Optional paged export capability; callers must coordinate index writes."""
        raise NotImplementedError('Vector backend does not support chunk export')
        yield  # pragma: no cover - Makes this an async iterator.

    @abstractmethod
    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    @abstractmethod
    async def search(
        self, query_embedding: list[float], *, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]: ...


class KeywordStore(ABC):
    @abstractmethod
    async def upsert(self, chunks: list[Chunk]) -> None: ...

    @abstractmethod
    async def search(
        self, query: str, *, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]: ...


class Reranker(ABC):
    @abstractmethod
    async def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]: ...


class QueryPlanner(ABC):
    @abstractmethod
    async def plan(self, query: Query) -> RetrievalPlan: ...


# Backwards-compatible name for integrations built against the first release.
QueryRouter = QueryPlanner


class Retriever(ABC):
    @abstractmethod
    async def retrieve(self, query: Query) -> RetrievalTrace: ...


class AnswerGenerator(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    def fallback_used(self) -> bool:
        return False

    @abstractmethod
    async def generate(self, query: Query, contexts: list[RetrievedChunk]) -> str: ...

    @abstractmethod
    def stream(self, query: Query, contexts: list[RetrievedChunk]) -> AsyncIterator[str]: ...


class StructuredOutputLLM(ABC):
    """Minimal LLM port for providers capable of schema-constrained JSON output."""

    @abstractmethod
    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]: ...
