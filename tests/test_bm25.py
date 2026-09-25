import pytest

from rag_framework.core.models import Chunk
from rag_framework.providers.bm25 import InMemoryBM25KeywordStore


def make_chunk(chunk_id: str, content: str, **metadata: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=f"doc-{chunk_id}",
        index=0,
        content=content,
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_bm25_ranks_exact_terms_and_preserves_scores() -> None:
    store = InMemoryBM25KeywordStore()
    await store.upsert(
        [
            make_chunk("a", "vector databases support semantic retrieval"),
            make_chunk("b", "BM25 keyword keyword keyword retrieval"),
        ]
    )

    results = await store.search("keyword retrieval", top_k=2, filters={})

    assert [result.chunk.id for result in results] == ["b", "a"]
    assert results[0].component_scores["keyword"] == results[0].score


@pytest.mark.asyncio
async def test_bm25_supports_cjk_and_metadata_filters() -> None:
    store = InMemoryBM25KeywordStore()
    await store.upsert(
        [
            make_chunk("zh", "混合检索结合向量与关键词", team="platform"),
            make_chunk("other", "关键词检索测试", team="search"),
        ]
    )

    results = await store.search("混合检索", top_k=5, filters={"team": "platform"})

    assert [result.chunk.id for result in results] == ["zh"]
