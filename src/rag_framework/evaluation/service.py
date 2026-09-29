"""Concurrent batch retrieval evaluation and bounded in-memory report storage."""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from pathlib import Path
from time import perf_counter, time

from rag_framework.contracts.providers import Retriever

from .metrics import compare_metrics, compute_retrieval_metrics
from .models import (
    AnyEvaluationReportSummary,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationReport,
    EvaluationReportSummary,
    MetricComparison,
    MetricDelta,
    RAGEvaluationReport,
    RAGEvaluationReportSummary,
    RetrievalEvaluationReport,
    RetrievalEvaluationRequest,
    RetrievalMetrics,
)
from .registry import average_extensions, retrieval_extensions, select_metrics


class EvaluationStore:
    def __init__(self, *, limit: int = 100, directory: Path | None = None) -> None:
        if limit < 1:
            raise ValueError("Evaluation report limit must be positive")
        self.limit = limit
        self.directory = directory
        self._reports: OrderedDict[str, EvaluationReport] = OrderedDict()
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._load()

    def save(self, report: EvaluationReport) -> None:
        self._reports[report.id] = report
        self._reports.move_to_end(report.id)
        if self.directory is not None:
            self._write(report)
        while len(self._reports) > self.limit:
            report_id, _ = self._reports.popitem(last=False)
            if self.directory is not None:
                self._path(report_id).unlink(missing_ok=True)

    def get(self, report_id: str) -> EvaluationReport | None:
        return self._reports.get(report_id)

    def list(self) -> list[AnyEvaluationReportSummary]:
        summaries: list[AnyEvaluationReportSummary] = []
        for report in reversed(self._reports.values()):
            summary_type = (
                RAGEvaluationReportSummary
                if isinstance(report, RAGEvaluationReport)
                else EvaluationReportSummary
            )
            summaries.append(summary_type.model_validate(report.model_dump(exclude={"cases"})))
        return summaries

    def _load(self) -> None:
        assert self.directory is not None
        reports: list[EvaluationReport] = []
        for path in self.directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text("utf-8"))
                if not isinstance(payload, dict):
                    continue
                report_type = (
                    RAGEvaluationReport
                    if payload.get("kind") == "rag"
                    else RetrievalEvaluationReport
                )
                reports.append(report_type.model_validate(payload))
            except (OSError, ValueError):
                continue
        for report in sorted(reports, key=lambda item: item.started_at):
            self._reports[report.id] = report
        while len(self._reports) > self.limit:
            report_id, _ = self._reports.popitem(last=False)
            self._path(report_id).unlink(missing_ok=True)

    def _write(self, report: EvaluationReport) -> None:
        path = self._path(report.id)
        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        temporary_path.replace(path)

    def _path(self, report_id: str) -> Path:
        assert self.directory is not None
        if not report_id or Path(report_id).name != report_id:
            raise ValueError("Invalid evaluation report id")
        return self.directory / f"{report_id}.json"


class RetrievalEvaluator:
    def __init__(
        self,
        retriever: Retriever,
        store: EvaluationStore,
        *,
        concurrency: int = 4,
        config_snapshot: dict | None = None,
        metrics: str = "",
    ) -> None:
        if concurrency < 1:
            raise ValueError("Evaluation concurrency must be positive")
        self.retriever = retriever
        self.store = store
        self.concurrency = concurrency
        self.config_snapshot = config_snapshot
        self.metric_names, _ = select_metrics(metrics)

    async def evaluate(self, request: RetrievalEvaluationRequest) -> RetrievalEvaluationReport:
        started_at = time()
        started = perf_counter()
        semaphore = asyncio.Semaphore(self.concurrency)

        async def limited(case: EvaluationCase) -> EvaluationCaseResult:
            async with semaphore:
                return await self._evaluate_case(case, request)

        results = await asyncio.gather(*(limited(case) for case in request.cases))
        comparisons = [result.metrics for result in results if result.metrics is not None]
        successful = len(comparisons)
        status = (
            "complete"
            if successful == len(results)
            else "partial"
            if successful
            else "failed"
        )
        report = RetrievalEvaluationReport(
            metric_extensions=average_extensions(results),
            config_snapshot=self.config_snapshot,
            knowledge_base_id=request.knowledge_base_id,
            status=status,
            k=request.k,
            case_count=len(results),
            successful_case_count=successful,
            dataset_id=request.dataset_id,
            metrics=average_metric_comparisons(comparisons) if comparisons else None,
            cases=results,
            started_at=started_at,
            duration_ms=(perf_counter() - started) * 1000,
        )
        self.store.save(report)
        return report

    async def _evaluate_case(
        self, case: EvaluationCase, request: RetrievalEvaluationRequest
    ) -> EvaluationCaseResult:
        try:
            trace = await self.retriever.retrieve(case.query)
            before_ids = [item.chunk.id for item in trace.candidates[: request.k]]
            after_ids = [item.chunk.id for item in trace.final_context[: request.k]]
            relevant = set(case.relevant_chunk_ids)
            before = compute_retrieval_metrics(before_ids, relevant, k=request.k)
            after = compute_retrieval_metrics(after_ids, relevant, k=request.k)
            return EvaluationCaseResult(
                metric_extensions=retrieval_extensions(self.metric_names, before_ids, after_ids, relevant, request.k),
                case_id=case.id,
                query=case.query.text,
                relevant_chunk_ids=case.relevant_chunk_ids,
                before_chunk_ids=before_ids,
                after_chunk_ids=after_ids,
                metrics=compare_metrics(before, after),
                trace_id=trace.id,
                trace=trace if request.include_trace else None,
            )
        except Exception as exc:  # noqa: BLE001 - A batch report must preserve other case results.
            return EvaluationCaseResult(
                case_id=case.id,
                query=case.query.text,
                relevant_chunk_ids=case.relevant_chunk_ids,
                error=type(exc).__name__,
            )


def average_metric_comparisons(comparisons: list[MetricComparison]) -> MetricComparison:
    before = _average_metrics([comparison.before for comparison in comparisons])
    after = _average_metrics([comparison.after for comparison in comparisons])
    delta_values = {
        field: getattr(after, field) - getattr(before, field)
        for field in RetrievalMetrics.model_fields
    }
    return MetricComparison(before=before, after=after, delta=MetricDelta(**delta_values))


def _average_metrics(metrics: list[RetrievalMetrics]) -> RetrievalMetrics:
    return RetrievalMetrics(
        **{
            field: sum(getattr(metric, field) for metric in metrics) / len(metrics)
            for field in RetrievalMetrics.model_fields
        }
    )
