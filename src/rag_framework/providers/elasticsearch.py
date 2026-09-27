"""Async Elasticsearch implementation of the keyword-store contract."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from rag_framework.contracts.providers import KeywordStore
from rag_framework.core.models import Chunk, RetrievedChunk

BulkWriter = Callable[..., Awaitable[Any]]


class ElasticsearchKeywordStore(KeywordStore):
    """Persistent BM25 retrieval using the official async Elasticsearch client."""

    def __init__(
        self,
        *,
        url: str,
        index_name: str,
        analyzer: str = "standard",
        bm25_k1: float = 1.2,
        bm25_b: float = 0.75,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_certs: bool = True,
        request_timeout: float = 10.0,
        client: Any | None = None,
        bulk_writer: BulkWriter | None = None,
    ) -> None:
        self.index_name = index_name
        self.analyzer = analyzer
        self.bm25_k1 = bm25_k1
        self.bm25_b = bm25_b
        self._initialization_lock = asyncio.Lock()
        self._initialized = False
        self._owns_client = client is None

        if client is None:
            try:
                from elasticsearch import AsyncElasticsearch
            except ImportError as error:
                raise RuntimeError(
                    "Elasticsearch support requires: pip install 'rag-framework[elasticsearch]'"
                ) from error

            client_options: dict[str, Any] = {
                "verify_certs": verify_certs,
                "request_timeout": request_timeout,
            }
            if api_key:
                client_options["api_key"] = api_key
            elif username:
                client_options["basic_auth"] = (username, password or "")
            client = AsyncElasticsearch(url, **client_options)

        if bulk_writer is None:
            try:
                from elasticsearch.helpers import async_bulk
            except ImportError as error:
                raise RuntimeError(
                    "Elasticsearch support requires: pip install 'rag-framework[elasticsearch]'"
                ) from error
            bulk_writer = async_bulk

        self._client = client
        self._bulk_writer = bulk_writer

    async def ensure_index(self) -> None:
        if self._initialized:
            return
        async with self._initialization_lock:
            if self._initialized:
                return
            exists = await self._client.indices.exists(index=self.index_name)
            if not bool(exists):
                await self._client.indices.create(
                    index=self.index_name,
                    settings={
                        "index": {
                            "similarity": {
                                "rag_bm25": {
                                    "type": "BM25",
                                    "k1": self.bm25_k1,
                                    "b": self.bm25_b,
                                }
                            }
                        }
                    },
                    mappings={
                        "dynamic": "strict",
                        "properties": {
                            "chunk_id": {"type": "keyword"},
                            "document_id": {"type": "keyword"},
                            "chunk_index": {"type": "integer"},
                            "content": {
                                "type": "text",
                                "analyzer": self.analyzer,
                                "similarity": "rag_bm25",
                            },
                            "source_uri": {"type": "keyword", "ignore_above": 2048},
                            "metadata": {"type": "flattened"},
                        },
                    },
                )
            self._initialized = True

    async def upsert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        await self.ensure_index()
        actions = [
            {
                "_op_type": "index",
                "_index": self.index_name,
                "_id": chunk.id,
                "_source": {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.index,
                    "content": chunk.content,
                    "source_uri": chunk.source_uri or "",
                    "metadata": chunk.metadata,
                },
            }
            for chunk in chunks
        ]
        await self._bulk_writer(self._client, actions, refresh="wait_for")

    async def search(
        self, query: str, *, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]:
        await self.ensure_index()
        bool_query: dict[str, Any] = {
            "must": [{"match": {"content": {"query": query}}}],
        }
        filter_queries = self._build_filters(filters)
        if filter_queries:
            bool_query["filter"] = filter_queries

        response = await self._client.search(
            index=self.index_name,
            size=top_k,
            query={"bool": bool_query},
        )
        body = response.body if hasattr(response, "body") else response
        hits = body.get("hits", {}).get("hits", [])
        return [self._to_result(hit, rank) for rank, hit in enumerate(hits, start=1)]

    async def health(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:  # noqa: BLE001 - Health checks convert provider failures to status.
            return False

    async def clear(self) -> int:
        exists = await self._client.indices.exists(index=self.index_name)
        if not bool(exists):
            self._initialized = False
            return 0
        response = await self._client.count(index=self.index_name)
        body = response.body if hasattr(response, "body") else response
        count = int(body.get("count", 0))
        await self._client.indices.delete(index=self.index_name)
        self._initialized = False
        return count

    async def count(self) -> int:
        exists = await self._client.indices.exists(index=self.index_name)
        if not bool(exists):
            return 0
        response = await self._client.count(index=self.index_name)
        body = response.body if hasattr(response, "body") else response
        return int(body.get("count", 0))

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    @staticmethod
    def _build_filters(filters: dict[str, object]) -> list[dict[str, Any]]:
        queries: list[dict[str, Any]] = []
        direct_fields = {"chunk_id", "document_id", "source_uri"}
        for key, expected in filters.items():
            field = key if key in direct_fields else f"metadata.{key}"
            if isinstance(expected, dict):
                if "$in" in expected:
                    queries.append({"terms": {field: expected["$in"]}})
                elif "$eq" in expected:
                    queries.append({"term": {field: expected["$eq"]}})
                else:
                    raise ValueError(f"Unsupported metadata filter for '{key}'")
            elif isinstance(expected, list):
                queries.append({"terms": {field: expected}})
            else:
                queries.append({"term": {field: expected}})
        return queries

    @staticmethod
    def _to_result(hit: dict[str, Any], rank: int) -> RetrievedChunk:
        source = hit.get("_source", {})
        score = float(hit.get("_score") or 0.0)
        return RetrievedChunk(
            chunk=Chunk(
                id=str(source.get("chunk_id") or hit.get("_id")),
                document_id=str(source["document_id"]),
                index=int(source["chunk_index"]),
                content=str(source["content"]),
                source_uri=source.get("source_uri") or None,
                metadata=dict(source.get("metadata") or {}),
            ),
            score=score,
            source="keyword:elasticsearch",
            rank=rank,
            component_scores={"keyword": score, "elasticsearch_bm25": score},
        )
