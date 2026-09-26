import math

import pytest

from rag_framework.contracts.providers import Retriever
from rag_framework.core.models import Chunk, Query, RetrievalTrace, RetrievedChunk
from rag_framework.evaluation import (
    EvaluationCase,
    EvaluationStore,
    RetrievalEvaluationRequest,
    RetrievalEvaluator,
    compute_retrieval_metrics,
)
from rag_framework.evaluation.metrics import compare_metrics


def _result(chunk_id: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id=chunk_id,
            document_id=f"doc-{chunk_id}",
            content=f"content for {chunk_id}",
            index=rank - 1,
        ),
        score=1.0 / rank,
        source="test",
        rank=rank,
    )


class StaticRetriever(Retriever):
    async def retrieve(self, query: Query) -> RetrievalTrace:
        if query.text == "fail":
            raise RuntimeError("provider details must not leak")
        candidates = [_result("irrelevant", 1), _result("relevant", 2)]
        final_context = [_result("relevant", 1), _result("irrelevant", 2)]
        return RetrievalTrace(
            query=query,
            candidates=candidates,
            final_context=final_context,
        )


def test_compute_retrieval_metrics() -> None:
    metrics = compute_retrieval_metrics(["a", "x", "b"], {"a", "b", "c"}, k=3)
    expected_ndcg = (1 + 1 / math.log2(4)) / (
        1 + 1 / math.log2(3) + 1 / math.log2(4)
    )

    assert metrics.hit_rate == 1
    assert metrics.precision_at_k == pytest.approx(2 / 3)
    assert metrics.recall_at_k == pytest.approx(2 / 3)
    assert metrics.mrr == 1
    assert metrics.ndcg_at_k == pytest.approx(expected_ndcg)


def test_metric_delta_allows_regression() -> None:
    better = compute_retrieval_metrics(["a"], {"a"}, k=1)
    worse = compute_retrieval_metrics(["x"], {"a"}, k=1)

    comparison = compare_metrics(better, worse)

    assert comparison.delta.hit_rate == -1
    assert comparison.delta.ndcg_at_k == -1


@pytest.mark.asyncio
async def test_evaluator_compares_before_and_after_rerank() -> None:
    store = EvaluationStore(limit=10)
    evaluator = RetrievalEvaluator(StaticRetriever(), store, concurrency=2)
    request = RetrievalEvaluationRequest(
        cases=[
            EvaluationCase(
                id="case-1",
                query=Query(text="find it"),
                relevant_chunk_ids=["relevant"],
            )
        ],
        k=1,
    )

    report = await evaluator.evaluate(request)

    assert report.status == "complete"
    assert report.successful_case_count == 1
    assert report.metrics is not None
    assert report.metrics.before.hit_rate == 0
    assert report.metrics.after.hit_rate == 1
    assert report.metrics.delta.mrr == 1
    assert report.cases[0].before_chunk_ids == ["irrelevant"]
    assert report.cases[0].after_chunk_ids == ["relevant"]
    assert report.cases[0].trace is None
    assert store.get(report.id) == report


@pytest.mark.asyncio
async def test_evaluator_can_include_trace_and_isolates_case_failures() -> None:
    evaluator = RetrievalEvaluator(StaticRetriever(), EvaluationStore(), concurrency=1)
    request = RetrievalEvaluationRequest(
        cases=[
            EvaluationCase(query=Query(text="ok"), relevant_chunk_ids=["relevant"]),
            EvaluationCase(query=Query(text="fail"), relevant_chunk_ids=["relevant"]),
        ],
        k=1,
        include_trace=True,
    )

    report = await evaluator.evaluate(request)

    assert report.status == "partial"
    assert report.successful_case_count == 1
    assert report.cases[0].trace is not None
    assert report.cases[1].error == "RuntimeError"
    assert "provider details" not in report.cases[1].error


@pytest.mark.asyncio
async def test_evaluation_store_evicts_oldest_and_lists_newest_first() -> None:
    store = EvaluationStore(limit=1)
    evaluator = RetrievalEvaluator(StaticRetriever(), store)
    first = await evaluator.evaluate(
        RetrievalEvaluationRequest(
            cases=[EvaluationCase(query=Query(text="first"), relevant_chunk_ids=["relevant"])]
        )
    )
    second = await evaluator.evaluate(
        RetrievalEvaluationRequest(
            cases=[EvaluationCase(query=Query(text="second"), relevant_chunk_ids=["relevant"])]
        )
    )

    assert store.get(first.id) is None
    assert store.get(second.id) == second
    assert [summary.id for summary in store.list()] == [second.id]


@pytest.mark.asyncio
async def test_evaluation_reports_survive_store_restart(tmp_path) -> None:
    store = EvaluationStore(limit=10, directory=tmp_path)
    evaluator = RetrievalEvaluator(StaticRetriever(), store)
    report = await evaluator.evaluate(
        RetrievalEvaluationRequest(
            cases=[EvaluationCase(query=Query(text="persist"), relevant_chunk_ids=["relevant"])],
            dataset_id="dataset-1",
        )
    )

    reloaded = EvaluationStore(limit=10, directory=tmp_path)

    assert reloaded.get(report.id) == report
    assert reloaded.list()[0].dataset_id == "dataset-1"


@pytest.mark.asyncio
async def test_persistent_store_removes_evicted_report_file(tmp_path) -> None:
    store = EvaluationStore(limit=1, directory=tmp_path)
    evaluator = RetrievalEvaluator(StaticRetriever(), store)
    first = await evaluator.evaluate(
        RetrievalEvaluationRequest(
            cases=[EvaluationCase(query=Query(text="first"), relevant_chunk_ids=["relevant"])]
        )
    )
    await evaluator.evaluate(
        RetrievalEvaluationRequest(
            cases=[EvaluationCase(query=Query(text="second"), relevant_chunk_ids=["relevant"])]
        )
    )

    assert not (tmp_path / f"{first.id}.json").exists()
