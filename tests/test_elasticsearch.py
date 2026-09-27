from typing import Any

import pytest

from rag_framework.contracts.providers import KeywordStore
from rag_framework.core.models import Chunk, RetrievedChunk
from rag_framework.providers.bm25 import InMemoryBM25KeywordStore
from rag_framework.providers.elasticsearch import ElasticsearchKeywordStore
from rag_framework.providers.resilient import ResilientKeywordStore


def make_chunk(chunk_id: str = "chunk-1") -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id="doc-1",
        index=2,
        content="Elasticsearch provides persistent BM25 retrieval.",
        source_uri="memory://document",
        metadata={"team": "search"},
    )


class FakeIndices:
    def __init__(self, exists: bool = False) -> None:
        self.exists_result = exists
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    async def exists(self, *, index: str) -> bool:
        return self.exists_result

    async def create(self, **kwargs: Any) -> None:
        self.created.append(kwargs)
        self.exists_result = True

    async def delete(self, *, index: str) -> None:
        self.deleted.append(index)
        self.exists_result = False


class FakeElasticsearchClient:
    def __init__(self, *, index_exists: bool = False) -> None:
        self.indices = FakeIndices(index_exists)
        self.search_calls: list[dict[str, Any]] = []
        self.closed = False

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        self.search_calls.append(kwargs)
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "chunk-1",
                        "_score": 4.2,
                        "_source": {
                            "chunk_id": "chunk-1",
                            "document_id": "doc-1",
                            "chunk_index": 2,
                            "content": "Elasticsearch provides persistent BM25 retrieval.",
                            "source_uri": "memory://document",
                            "metadata": {"team": "search"},
                        },
                    }
                ]
            }
        }

    async def ping(self) -> bool:
        return True

    async def count(self, *, index: str) -> dict[str, int]:
        return {"count": 3}

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_elasticsearch_creates_mapping_and_bulk_indexes_chunks() -> None:
    client = FakeElasticsearchClient()
    bulk_calls: list[dict[str, Any]] = []

    async def bulk_writer(client: Any, actions: list[dict[str, Any]], **kwargs: Any) -> None:
        bulk_calls.append({"client": client, "actions": actions, **kwargs})

    store = ElasticsearchKeywordStore(
        url="http://unused:9200",
        index_name="rag-test",
        analyzer="standard",
        client=client,
        bulk_writer=bulk_writer,
    )
    await store.upsert([make_chunk()])

    mapping = client.indices.created[0]
    assert mapping["mappings"]["properties"]["content"]["similarity"] == "rag_bm25"
    assert mapping["mappings"]["properties"]["metadata"]["type"] == "flattened"
    assert bulk_calls[0]["refresh"] == "wait_for"
    assert bulk_calls[0]["actions"][0]["_id"] == "chunk-1"


@pytest.mark.asyncio
async def test_elasticsearch_search_builds_filters_and_restores_chunk() -> None:
    client = FakeElasticsearchClient(index_exists=True)

    async def unused_bulk_writer(*args: Any, **kwargs: Any) -> None:
        return None

    store = ElasticsearchKeywordStore(
        url="http://unused:9200",
        index_name="rag-test",
        client=client,
        bulk_writer=unused_bulk_writer,
    )
    results = await store.search(
        "persistent retrieval",
        top_k=3,
        filters={"team": "search", "document_id": {"$in": ["doc-1"]}},
    )

    request = client.search_calls[0]
    assert request["query"]["bool"]["filter"] == [
        {"term": {"metadata.team": "search"}},
        {"terms": {"document_id": ["doc-1"]}},
    ]
    assert results[0].chunk == make_chunk()
    assert results[0].source == "keyword:elasticsearch"
    assert results[0].component_scores["elasticsearch_bm25"] == 4.2


@pytest.mark.asyncio
async def test_elasticsearch_clear_deletes_only_configured_index() -> None:
    client = FakeElasticsearchClient(index_exists=True)

    async def unused_bulk_writer(*args: Any, **kwargs: Any) -> None:
        return None

    store = ElasticsearchKeywordStore(
        url="http://unused:9200", index_name="rag-test", client=client,
        bulk_writer=unused_bulk_writer,
    )
    assert await store.clear() == 3
    assert client.indices.deleted == ["rag-test"]
    assert await store.count() == 0


class FailingKeywordStore(KeywordStore):
    async def upsert(self, chunks: list[Chunk]) -> None:
        raise ConnectionError("Elasticsearch unavailable")

    async def search(
        self, query: str, *, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]:
        raise ConnectionError("Elasticsearch unavailable")


@pytest.mark.asyncio
async def test_resilient_store_mirrors_and_falls_back_to_memory() -> None:
    store = ResilientKeywordStore(FailingKeywordStore(), InMemoryBM25KeywordStore())
    await store.upsert([make_chunk()])

    results = await store.search("persistent BM25", top_k=3, filters={})

    assert results[0].chunk.id == "chunk-1"
    assert results[0].source == "keyword:memory:fallback"
