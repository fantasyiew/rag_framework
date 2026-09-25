import pytest
from test_retrieval import StubEmbedder, StubRouter, StubVectorStore, make_result

from rag_framework.core.models import Query, RetrievalStrategy
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers.rerank import CrossEncoderReranker


class Scores:
    def __init__(self, values):
        self.values = values

    def predict(self, pairs, **kwargs):
        assert len(pairs) == 4
        return self.values


class EnabledRouter(StubRouter):
    async def plan(self, query):
        plan = await super().plan(query)
        plan.decision.rerank = True
        return plan


def pipeline(values, *, fail_open=True):
    return AdaptiveRetriever(
        StubVectorStore([make_result(str(i)) for i in range(4)]),
        StubEmbedder(), EnabledRouter(RetrievalStrategy.VECTOR),
        reranker=CrossEncoderReranker("fake", model=Scores(values)),
        reranker_candidate_k=4, reranker_fail_open=fail_open,
    )


@pytest.mark.asyncio
async def test_rerank_expands_pool_preserves_snapshot_and_promotes_fourth_candidate():
    trace = await pipeline([0.1, 0.2, 0.3, 0.9]).retrieve(Query(text="test"))
    assert [item.chunk.id for item in trace.final_context] == ["3", "2", "1"]
    assert [item.score for item in trace.candidates] == [0.8] * 4
    change = trace.rerank_comparison.changes[0]
    assert (change.original_rank, change.final_rank) == (4, 1)
    assert trace.final_context[0].component_scores == {"vector": 0.8, "rerank": 0.9}


@pytest.mark.asyncio
@pytest.mark.parametrize("scores", [[float("nan")] * 4, [0.5]])
async def test_invalid_scores_restore_original_order(scores):
    trace = await pipeline(scores).retrieve(Query(text="test"))
    assert [item.chunk.id for item in trace.final_context] == ["0", "1", "2"]
    assert trace.rerank_comparison.fallback_used
    assert trace.rerank_comparison.fallback_reason == "ValueError"


@pytest.mark.asyncio
async def test_strict_mode_propagates_error():
    with pytest.raises(ValueError):
        await pipeline([0.5], fail_open=False).retrieve(Query(text="test"))


@pytest.mark.asyncio
async def test_empty_candidates_do_not_load_model():
    reranker = CrossEncoderReranker("not-installed")
    assert await reranker.rerank("test", []) == []
    assert reranker._model is None
