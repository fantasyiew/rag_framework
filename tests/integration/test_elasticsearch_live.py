import os
from uuid import uuid4

import pytest

from rag_framework.core.models import Chunk
from rag_framework.providers.elasticsearch import ElasticsearchKeywordStore


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_elasticsearch_bm25_and_filters() -> None:
    url = os.getenv("RAG_TEST_ELASTICSEARCH_URL")
    if not url:
        pytest.skip("Set RAG_TEST_ELASTICSEARCH_URL to run live Elasticsearch tests")

    from elasticsearch import AsyncElasticsearch

    index_name = f"rag-framework-integration-{uuid4().hex}"
    client = AsyncElasticsearch(url)
    store = ElasticsearchKeywordStore(
        url=url,
        index_name=index_name,
        client=client,
    )
    chunks = [
        Chunk(
            id="exact",
            document_id="doc-search",
            index=0,
            content="Elasticsearch BM25 exact keyword retrieval keyword",
            metadata={"team": "search"},
        ),
        Chunk(
            id="semantic",
            document_id="doc-platform",
            index=0,
            content="Vector databases represent semantic relationships",
            metadata={"team": "platform"},
        ),
    ]

    try:
        await store.upsert(chunks)

        results = await store.search("keyword retrieval", top_k=5, filters={})
        filtered = await store.search(
            "Elasticsearch",
            top_k=5,
            filters={"team": "search", "document_id": {"$in": ["doc-search"]}},
        )
        settings = await client.indices.get_settings(index=index_name)

        assert await store.health() is True
        assert results[0].chunk.id == "exact"
        assert results[0].source == "keyword:elasticsearch"
        assert [result.chunk.id for result in filtered] == ["exact"]
        assert settings[index_name]["settings"]["index"]["similarity"]["rag_bm25"]["type"] == "BM25"
    finally:
        try:
            await client.indices.delete(index=index_name, ignore_unavailable=True)
        finally:
            await client.close()
