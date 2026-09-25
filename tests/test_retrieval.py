import pytest

from rag_framework.contracts.providers import Embedder, QueryRouter, VectorStore
from rag_framework.core.models import (
    Chunk,
    Query,
    QueryType,
    RetrievalPlan,
    RetrievalStrategy,
    RetrievedChunk,
)
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers.bm25 import InMemoryBM25KeywordStore


class StubEmbedder(Embedder):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0]


class StubVectorStore(VectorStore):
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.search_count = 0

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        return None

    async def search(
        self, query_embedding: list[float], *, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]:
        self.search_count += 1
        return self.results[:top_k]


class StubRouter(QueryRouter):
    def __init__(self, strategy: RetrievalStrategy) -> None:
        self.strategy = strategy

    async def plan(self, query: Query) -> RetrievalPlan:
        return RetrievalPlan(
            query_type=QueryType.FACT_LOOKUP,
            strategy=self.strategy,
            top_k=3,
            rerank=False,
        )


def make_result(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id=chunk_id,
            document_id=f"doc-{chunk_id}",
            index=0,
            content="hybrid retrieval combines semantic and keyword evidence",
        ),
        score=0.8,
        source="vector",
        rank=1,
        component_scores={"vector": 0.8},
    )


@pytest.mark.asyncio
async def test_hybrid_strategy_runs_both_retrievers_and_records_fusion() -> None:
    vector_store = StubVectorStore([make_result("shared")])
    keyword_store = InMemoryBM25KeywordStore()
    await keyword_store.upsert([make_result("shared").chunk, make_result("keyword").chunk])
    retriever = AdaptiveRetriever(
        vector_store,
        StubEmbedder(),
        StubRouter(RetrievalStrategy.HYBRID),
        keyword_store,
    )

    trace = await retriever.retrieve(Query(text="keyword evidence"))

    assert vector_store.search_count == 1
    assert trace.final_context[0].source == "hybrid"
    assert [step.name for step in trace.steps] == ["route_query", "hybrid_recall", "rrf_fusion"]


@pytest.mark.asyncio
async def test_keyword_strategy_does_not_call_vector_store() -> None:
    vector_store = StubVectorStore([make_result("vector")])
    keyword_store = InMemoryBM25KeywordStore()
    await keyword_store.upsert([make_result("keyword").chunk])
    retriever = AdaptiveRetriever(
        vector_store,
        StubEmbedder(),
        StubRouter(RetrievalStrategy.KEYWORD),
        keyword_store,
    )

    trace = await retriever.retrieve(Query(text="keyword"))

    assert vector_store.search_count == 0
    assert trace.final_context[0].source == "keyword:memory"
    assert trace.steps[-1].name == "keyword_search"
