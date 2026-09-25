"""Ports used by the pipeline. Provider implementations depend on these, never vice versa."""

from __future__ import annotations

from abc import ABC, abstractmethod

from rag_framework.core.models import Chunk, Query, RetrievalPlan, RetrievedChunk


class Embedder(ABC):
    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...


class VectorStore(ABC):
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


class QueryRouter(ABC):
    @abstractmethod
    async def plan(self, query: Query) -> RetrievalPlan: ...


class StructuredOutputLLM(ABC):
    """Minimal LLM port for providers capable of schema-constrained JSON output."""

    @abstractmethod
    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]: ...
