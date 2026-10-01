import pytest
from test_retrieval import StubEmbedder, StubVectorStore, make_result

from rag_framework.core.models import Query, RetrievalStrategy
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers.bm25 import InMemoryBM25KeywordStore
from rag_framework.providers.fixed_planner import FixedQueryPlanner
from rag_framework.providers.generation import ExtractiveAnswerGenerator


class ReverseReranker:
    async def rerank(self, query, candidates):
        return list(reversed(candidates))


@pytest.mark.parametrize('strategy', list(RetrievalStrategy))
@pytest.mark.parametrize('rerank', [True, False])
@pytest.mark.parametrize('limit,expected', [(6, 6), (None, 8), (0, 8), (10, 8)])
async def test_hard_limit_and_planner_control(strategy, rerank, limit, expected):
    results = [make_result(str(index)) for index in range(12)]
    keywords = InMemoryBM25KeywordStore()
    await keywords.upsert([item.chunk for item in results])
    retriever = AdaptiveRetriever(
        StubVectorStore(results), StubEmbedder(),
        FixedQueryPlanner(strategy, 8, rerank), keywords,
        reranker=ReverseReranker() if rerank else None,
        reranker_candidate_k=12, top_k_limit=limit,
    )
    response = await GenerationPipeline(
        retriever, ExtractiveAnswerGenerator(), max_context_chunks=8,
    ).run(Query(text='keyword evidence'))
    assert len(response.retrieval.final_context) == expected
    step = next(s for s in response.retrieval.steps if s.name == 'select_retrieval_strategy')
    assert step.details['planned_top_k'] == 8
    assert step.details['effective_top_k'] == expected
    assert response.retrieval.steps[-1].details['context_count'] == expected
    if rerank:
        assert len(response.retrieval.candidates) > expected


async def test_generation_can_further_limit_unlimited_retrieval():
    retriever = AdaptiveRetriever(
        StubVectorStore([make_result(str(i)) for i in range(12)]), StubEmbedder(),
        FixedQueryPlanner('vector', 10, False), top_k_limit=None,
    )
    pipeline = GenerationPipeline(retriever, ExtractiveAnswerGenerator(), max_context_chunks=8)
    events = [event async for event in pipeline.stream(Query(text='query'))]
    assert events[0].data['context_count'] == 8
    assert len(events[-1].data['trace']['final_context']) == 10
    assert events[-1].data['trace']['steps'][-1]['details']['context_count'] == 8
