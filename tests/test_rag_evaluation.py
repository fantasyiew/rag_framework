from collections.abc import AsyncIterator

import pytest

from rag_framework.contracts.providers import AnswerGenerator, Retriever
from rag_framework.core.models import (
    Chunk,
    GeneratedAnswer,
    Query,
    RAGResponse,
    RetrievalTrace,
    RetrievedChunk,
)
from rag_framework.evaluation import (
    EvaluationCase,
    EvaluationStore,
    RAGEvaluationRequest,
    RAGEvaluator,
    compute_answer_quality,
)
from rag_framework.pipeline.generation import GenerationPipeline


def _result(chunk_id: str, content: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id=chunk_id,
            document_id=f"doc-{chunk_id}",
            content=content,
            index=rank - 1,
        ),
        score=1.0 / rank,
        source="test",
        rank=rank,
    )


class EvaluationRetriever(Retriever):
    async def retrieve(self, query: Query) -> RetrievalTrace:
        if query.text == "fail":
            raise RuntimeError("provider unavailable")
        relevant = _result("relevant", "Tokyo Tower is 333 meters tall.", 1)
        irrelevant = _result("irrelevant", "Kyoto has many historic temples.", 2)
        return RetrievalTrace(
            query=query,
            candidates=[irrelevant, relevant],
            final_context=[relevant, irrelevant],
        )


class EvaluationGenerator(AnswerGenerator):
    @property
    def model_name(self) -> str:
        return "evaluation-generator"

    async def generate(self, query: Query, contexts: list[RetrievedChunk]) -> str:
        return "Tokyo Tower is 333 meters tall [1]."

    async def stream(
        self,
        query: Query,
        contexts: list[RetrievedChunk],
    ) -> AsyncIterator[str]:
        yield await self.generate(query, contexts)


async def test_registered_answer_metrics_and_missing_reference():
    evaluator = RAGEvaluator(GenerationPipeline(EvaluationRetriever(), EvaluationGenerator()),
        EvaluationStore(), metrics='answer.reference_similarity,answer.groundedness,retrieval.mrr')
    report = await evaluator.evaluate(RAGEvaluationRequest(cases=[EvaluationCase(
        query=Query(text='How tall is Tokyo Tower?'), relevant_chunk_ids=['relevant'])]))
    assert report.status == 'complete'
    assert report.metric_extensions['answer.reference_similarity'] is None
    assert report.metric_extensions['answer.groundedness'] == report.answer_metrics.groundedness
    assert report.metric_extensions['retrieval.mrr.delta'] == 0.5


def test_answer_quality_scores_grounding_relevancy_and_citations() -> None:
    context = _result("relevant", "Tokyo Tower is 333 meters tall.", 1)
    trace = RetrievalTrace(query=Query(text="How tall is Tokyo Tower?"), final_context=[context])
    trace.add_step("generate_answer", 1.0, context_count=1)
    response = RAGResponse(
        retrieval=trace,
        answer=GeneratedAnswer(
            text="Tokyo Tower is 333 meters tall [1] [9].",
            model="test",
        ),
    )
    case = EvaluationCase(
        query=trace.query,
        relevant_chunk_ids=["relevant"],
        reference_answer="Tokyo Tower is 333 meters tall.",
    )

    metrics = compute_answer_quality(case, response)

    assert metrics.method == "heuristic_v1"
    assert metrics.groundedness == 1
    assert metrics.answer_relevancy > 0.7
    assert metrics.citation_validity == 0.5
    assert metrics.citation_precision == 1
    assert metrics.citation_recall == 1
    assert metrics.reference_similarity == 1


def test_citation_validity_uses_the_context_window_seen_by_generator() -> None:
    contexts = [_result(f"chunk-{index}", f"content {index}", index) for index in range(1, 10)]
    trace = RetrievalTrace(query=Query(text="question"), final_context=contexts)
    trace.add_step("generate_answer", 1.0, context_count=1)
    response = RAGResponse(
        retrieval=trace,
        answer=GeneratedAnswer(text="Unsupported citation [9].", model="test"),
    )
    case = EvaluationCase(query=trace.query, relevant_chunk_ids=["chunk-1"])

    metrics = compute_answer_quality(case, response)

    assert metrics.citation_validity == 0
    assert metrics.citation_precision == 0
    assert metrics.citation_recall == 0


@pytest.mark.asyncio
async def test_rag_evaluator_combines_retrieval_and_answer_metrics(tmp_path) -> None:
    store = EvaluationStore(limit=10, directory=tmp_path)
    pipeline = GenerationPipeline(EvaluationRetriever(), EvaluationGenerator())
    evaluator = RAGEvaluator(pipeline, store, concurrency=2)
    request = RAGEvaluationRequest(
        cases=[
            EvaluationCase(
                id="case-1",
                query=Query(text="How tall is Tokyo Tower?"),
                relevant_chunk_ids=["relevant"],
                reference_answer="Tokyo Tower is 333 meters tall.",
            )
        ],
        k=1,
        dataset_id="dataset-1",
    )

    report = await evaluator.evaluate(request)
    reloaded_store = EvaluationStore(limit=10, directory=tmp_path)
    reloaded = reloaded_store.get(report.id)

    assert report.kind == "rag"
    assert report.status == "complete"
    assert report.retrieval_metrics is not None
    assert report.retrieval_metrics.before.hit_rate == 0
    assert report.retrieval_metrics.after.hit_rate == 1
    assert report.answer_metrics is not None
    assert report.answer_metrics.groundedness == 1
    assert report.cases[0].answer is not None
    assert report.cases[0].trace is None
    assert reloaded == report
    assert reloaded_store.list()[0].kind == "rag"


@pytest.mark.asyncio
async def test_rag_evaluator_isolates_generation_failures() -> None:
    evaluator = RAGEvaluator(
        GenerationPipeline(EvaluationRetriever(), EvaluationGenerator()),
        EvaluationStore(),
    )
    request = RAGEvaluationRequest(
        cases=[
            EvaluationCase(query=Query(text="ok"), relevant_chunk_ids=["relevant"]),
            EvaluationCase(query=Query(text="fail"), relevant_chunk_ids=["relevant"]),
        ]
    )

    report = await evaluator.evaluate(request)

    assert report.status == "partial"
    assert report.successful_case_count == 1
    assert report.cases[1].error == "RuntimeError"
