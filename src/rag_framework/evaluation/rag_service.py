"""End-to-end RAG evaluation over retrieval and generated answers."""

from __future__ import annotations

import asyncio
from time import perf_counter, time

from rag_framework.core.models import RetrievedChunk
from rag_framework.pipeline.generation import GenerationPipeline

from .answer_metrics import average_answer_quality
from .judges import AnswerJudge, HeuristicAnswerJudge
from .metrics import compare_metrics, compute_retrieval_metrics
from .models import (
    EvaluationCase,
    MetricComparison,
    RAGEvaluationCaseResult,
    RAGEvaluationReport,
    RAGEvaluationRequest,
)
from .service import EvaluationStore, average_metric_comparisons


class RAGEvaluator:
    def __init__(
        self,
        pipeline: GenerationPipeline,
        store: EvaluationStore,
        *,
        concurrency: int = 4,
        judge: AnswerJudge | None = None,
        config_snapshot: dict | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("Evaluation concurrency must be positive")
        self.pipeline = pipeline
        self.store = store
        self.concurrency = concurrency
        self.judge = judge or HeuristicAnswerJudge()
        self.config_snapshot = config_snapshot

    async def evaluate(self, request: RAGEvaluationRequest) -> RAGEvaluationReport:
        started_at = time()
        started = perf_counter()
        semaphore = asyncio.Semaphore(self.concurrency)

        async def limited(case: EvaluationCase) -> RAGEvaluationCaseResult:
            async with semaphore:
                return await self._evaluate_case(case, request)

        results = await asyncio.gather(*(limited(case) for case in request.cases))
        successful_results = [result for result in results if result.answer_metrics is not None]
        successful = len(successful_results)
        status = (
            "complete"
            if successful == len(results)
            else "partial"
            if successful
            else "failed"
        )
        retrieval_metrics = [
            result.retrieval_metrics
            for result in successful_results
            if result.retrieval_metrics is not None
        ]
        answer_metrics = [
            result.answer_metrics
            for result in successful_results
            if result.answer_metrics is not None
        ]
        report = RAGEvaluationReport(
            config_snapshot=self.config_snapshot,
            knowledge_base_id=request.knowledge_base_id,
            status=status,
            k=request.k,
            case_count=len(results),
            successful_case_count=successful,
            dataset_id=request.dataset_id,
            retrieval_metrics=(
                average_metric_comparisons(retrieval_metrics) if retrieval_metrics else None
            ),
            answer_metrics=average_answer_quality(answer_metrics) if answer_metrics else None,
            cases=results,
            started_at=started_at,
            duration_ms=(perf_counter() - started) * 1000,
        )
        self.store.save(report)
        return report

    async def _evaluate_case(
        self,
        case: EvaluationCase,
        request: RAGEvaluationRequest,
    ) -> RAGEvaluationCaseResult:
        try:
            response = await self.pipeline.run(case.query)
            trace = response.retrieval
            retrieval_metrics = _retrieval_comparison(case, trace.candidates, trace.final_context, request.k)
            return RAGEvaluationCaseResult(
                case_id=case.id,
                query=case.query.text,
                relevant_chunk_ids=case.relevant_chunk_ids,
                reference_answer=case.reference_answer,
                retrieval_metrics=retrieval_metrics,
                answer_metrics=await self.judge.evaluate(case, response),
                answer=response.answer,
                trace_id=trace.id,
                trace=trace if request.include_trace else None,
            )
        except Exception as exc:  # noqa: BLE001 - One provider failure must not abort the batch.
            return RAGEvaluationCaseResult(
                case_id=case.id,
                query=case.query.text,
                relevant_chunk_ids=case.relevant_chunk_ids,
                reference_answer=case.reference_answer,
                error=type(exc).__name__,
            )


def _retrieval_comparison(
    case: EvaluationCase,
    candidates: list[RetrievedChunk],
    final_context: list[RetrievedChunk],
    k: int,
) -> MetricComparison:
    relevant = set(case.relevant_chunk_ids)
    before = compute_retrieval_metrics(
        [item.chunk.id for item in candidates[:k]],
        relevant,
        k=k,
    )
    after = compute_retrieval_metrics(
        [item.chunk.id for item in final_context[:k]],
        relevant,
        k=k,
    )
    return compare_metrics(before, after)
