"""Models for repeatable retrieval and rerank evaluation."""

from __future__ import annotations

from time import time
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from rag_framework.core.models import GeneratedAnswer, Query, RetrievalTrace


class EvaluationCase(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    query: Query
    relevant_chunk_ids: list[str] = Field(min_length=1)
    reference_answer: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("relevant_chunk_ids")
    @classmethod
    def normalize_relevant_ids(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not normalized:
            raise ValueError("At least one non-empty relevant chunk id is required")
        return normalized


class RetrievalEvaluationRequest(BaseModel):
    cases: list[EvaluationCase] = Field(min_length=1)
    knowledge_base_id: str = Field(default="default", min_length=1, max_length=64)
    k: int = Field(default=5, ge=1, le=100)
    include_trace: bool = False
    dataset_id: str | None = None


class DatasetEvaluationRequest(BaseModel):
    knowledge_base_id: str = Field(default="default", min_length=1, max_length=64)
    k: int = Field(default=5, ge=1, le=100)
    include_trace: bool = False


class RAGEvaluationRequest(BaseModel):
    cases: list[EvaluationCase] = Field(min_length=1)
    knowledge_base_id: str = Field(default="default", min_length=1, max_length=64)
    k: int = Field(default=5, ge=1, le=100)
    include_trace: bool = False
    dataset_id: str | None = None


class EvaluationDataset(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    cases: list[EvaluationCase] = Field(min_length=1)
    created_at: float = Field(default_factory=time)
    updated_at: float = Field(default_factory=time)

    @field_validator("cases")
    @classmethod
    def require_unique_case_ids(cls, cases: list[EvaluationCase]) -> list[EvaluationCase]:
        case_ids = [case.id for case in cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Evaluation case ids must be unique within a dataset")
        return cases


class EvaluationDatasetSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    case_count: int
    created_at: float
    updated_at: float


class RetrievalMetrics(BaseModel):
    hit_rate: float = Field(ge=0.0, le=1.0)
    precision_at_k: float = Field(ge=0.0, le=1.0)
    recall_at_k: float = Field(ge=0.0, le=1.0)
    mrr: float = Field(ge=0.0, le=1.0)
    ndcg_at_k: float = Field(ge=0.0, le=1.0)


class MetricDelta(BaseModel):
    hit_rate: float
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg_at_k: float


class MetricComparison(BaseModel):
    before: RetrievalMetrics
    after: RetrievalMetrics
    delta: MetricDelta


class AnswerQualityMetrics(BaseModel):
    method: Literal["heuristic_v1", "llm_judge_v1", "mixed"] = "heuristic_v1"
    fallback_used: bool = False
    fallback_reason: str | None = None
    groundedness: float = Field(ge=0.0, le=1.0)
    answer_relevancy: float = Field(ge=0.0, le=1.0)
    citation_validity: float = Field(ge=0.0, le=1.0)
    citation_correctness: float = Field(default=0.0, ge=0.0, le=1.0)
    citation_precision: float = Field(ge=0.0, le=1.0)
    citation_recall: float = Field(ge=0.0, le=1.0)
    reference_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    judge_rationale: str | None = None


class EvaluationCaseResult(BaseModel):
    metric_extensions: dict[str, float | None] = Field(default_factory=dict)
    case_id: str
    query: str
    relevant_chunk_ids: list[str]
    before_chunk_ids: list[str] = Field(default_factory=list)
    after_chunk_ids: list[str] = Field(default_factory=list)
    metrics: MetricComparison | None = None
    trace_id: str | None = None
    trace: RetrievalTrace | None = None
    error: str | None = None


class RetrievalEvaluationReport(BaseModel):
    metric_extensions: dict[str, float | None] = Field(default_factory=dict)
    config_snapshot: dict[str, Any] | None = None
    knowledge_base_id: str = "default"
    kind: Literal["retrieval"] = "retrieval"
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: Literal["complete", "partial", "failed"]
    k: int
    case_count: int
    successful_case_count: int
    dataset_id: str | None = None
    metrics: MetricComparison | None = None
    cases: list[EvaluationCaseResult]
    started_at: float = Field(default_factory=time)
    duration_ms: float = Field(ge=0.0)


class EvaluationReportSummary(BaseModel):
    kind: Literal["retrieval"] = "retrieval"
    id: str
    status: Literal["complete", "partial", "failed"]
    k: int
    case_count: int
    successful_case_count: int
    dataset_id: str | None = None
    metrics: MetricComparison | None = None
    started_at: float
    duration_ms: float


class RAGEvaluationCaseResult(BaseModel):
    metric_extensions: dict[str, float | None] = Field(default_factory=dict)
    case_id: str
    query: str
    relevant_chunk_ids: list[str]
    reference_answer: str | None = None
    retrieval_metrics: MetricComparison | None = None
    answer_metrics: AnswerQualityMetrics | None = None
    answer: GeneratedAnswer | None = None
    trace_id: str | None = None
    trace: RetrievalTrace | None = None
    error: str | None = None


class RAGEvaluationReport(BaseModel):
    metric_extensions: dict[str, float | None] = Field(default_factory=dict)
    config_snapshot: dict[str, Any] | None = None
    knowledge_base_id: str = "default"
    kind: Literal["rag"] = "rag"
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: Literal["complete", "partial", "failed"]
    k: int
    case_count: int
    successful_case_count: int
    dataset_id: str | None = None
    retrieval_metrics: MetricComparison | None = None
    answer_metrics: AnswerQualityMetrics | None = None
    cases: list[RAGEvaluationCaseResult]
    started_at: float = Field(default_factory=time)
    duration_ms: float = Field(ge=0.0)


class RAGEvaluationReportSummary(BaseModel):
    kind: Literal["rag"] = "rag"
    id: str
    status: Literal["complete", "partial", "failed"]
    k: int
    case_count: int
    successful_case_count: int
    dataset_id: str | None = None
    retrieval_metrics: MetricComparison | None = None
    answer_metrics: AnswerQualityMetrics | None = None
    started_at: float
    duration_ms: float


EvaluationReport = RetrievalEvaluationReport | RAGEvaluationReport
AnyEvaluationReportSummary = EvaluationReportSummary | RAGEvaluationReportSummary
