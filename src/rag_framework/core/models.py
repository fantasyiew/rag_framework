"""Framework-wide value objects with no domain or provider dependency."""

from __future__ import annotations

from enum import Enum
from time import time
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class QueryType(str, Enum):
    EXACT_MATCH = "exact_match"
    FACT_LOOKUP = "fact_lookup"
    SEMANTIC_QUESTION = "semantic_question"
    FILTERED_SEARCH = "filtered_search"
    COMPARISON = "comparison"
    MULTI_HOP = "multi_hop"
    CONVERSATION_FOLLOWUP = "conversation_followup"
    AMBIGUOUS = "ambiguous"


class RetrievalStrategy(str, Enum):
    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


class Document(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str = Field(min_length=1)
    source_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(Document):
    document_id: str
    index: int = Field(ge=0)


class Query(BaseModel):
    text: str = Field(min_length=1)
    conversation_id: str | None = None
    history: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)


class QueryAnalysis(BaseModel):
    query_type: QueryType
    normalized_query: str = Field(min_length=1)
    rewrite_required: bool = False
    rewritten_queries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class RetrievalDecision(BaseModel):
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    top_k: int = Field(default=8, ge=1, le=100)
    rerank: bool = True
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class RetrievalPlan(BaseModel):
    """Structured planner result with compatibility for the original flat schema."""

    analysis: QueryAnalysis
    decision: RetrievalDecision
    planner: str = "unknown"
    fallback_used: bool = False
    fallback_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_flat_plan(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "analysis" in value:
            return value
        query_type = value.get("query_type", QueryType.AMBIGUOUS)
        normalized_query = value.get("normalized_query") or value.get("original_query") or "unknown"
        return {
            "analysis": {
                "query_type": query_type,
                "normalized_query": normalized_query,
                "rewrite_required": value.get("rewrite_required", False),
                "rewritten_queries": value.get("rewritten_queries", []),
                "keywords": value.get("keywords", []),
                "filters": value.get("filters", {}),
                "reason": value.get("analysis_reason", value.get("reason", "")),
                "confidence": value.get("analysis_confidence", value.get("confidence", 0.0)),
            },
            "decision": {
                "strategy": value.get("strategy", RetrievalStrategy.HYBRID),
                "top_k": value.get("top_k", 8),
                "rerank": value.get("rerank", True),
                "reason": value.get("decision_reason", value.get("reason", "")),
                "confidence": value.get("decision_confidence", value.get("confidence", 0.0)),
            },
            "planner": value.get("planner", "legacy"),
            "fallback_used": value.get("fallback_used", False),
            "fallback_reason": value.get("fallback_reason"),
        }

    @property
    def query_type(self) -> QueryType:
        return self.analysis.query_type

    @property
    def strategy(self) -> RetrievalStrategy:
        return self.decision.strategy

    @property
    def top_k(self) -> int:
        return self.decision.top_k

    @property
    def rerank(self) -> bool:
        return self.decision.rerank

    @property
    def rewrite_required(self) -> bool:
        return self.analysis.rewrite_required

    @property
    def rewritten_queries(self) -> list[str]:
        return self.analysis.rewritten_queries

    @property
    def filters(self) -> dict[str, Any]:
        return self.analysis.filters

    @property
    def reason(self) -> str:
        return self.decision.reason

    @property
    def confidence(self) -> float:
        return self.decision.confidence


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    source: str
    rank: int = Field(ge=1)
    component_scores: dict[str, float] = Field(default_factory=dict)


class RankChange(BaseModel):
    chunk_id: str
    original_rank: int
    final_rank: int
    original_score: float
    rerank_score: float | None = None


class RerankComparison(BaseModel):
    model: str
    fallback_used: bool = False
    fallback_reason: str | None = None
    changes: list[RankChange] = Field(default_factory=list)


class TraceStep(BaseModel):
    name: str
    duration_ms: float = Field(ge=0)
    details: dict[str, Any] = Field(default_factory=dict)


class RetrievalTrace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    query: Query
    plan: RetrievalPlan | None = None
    rerank_comparison: RerankComparison | None = None
    retrieval_queries: list[str] = Field(default_factory=list)
    candidates: list[RetrievedChunk] = Field(default_factory=list)
    final_context: list[RetrievedChunk] = Field(default_factory=list)
    steps: list[TraceStep] = Field(default_factory=list)
    started_at: float = Field(default_factory=time)

    def add_step(self, name: str, duration_ms: float, **details: Any) -> None:
        self.steps.append(TraceStep(name=name, duration_ms=duration_ms, details=details))


class Citation(BaseModel):
    number: int = Field(ge=1)
    chunk_id: str
    document_id: str
    source_uri: str | None = None
    content_preview: str


class GeneratedAnswer(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)
    model: str
    fallback_used: bool = False


class RAGResponse(BaseModel):
    retrieval: RetrievalTrace
    answer: GeneratedAnswer


class RAGStreamEvent(BaseModel):
    type: Literal["retrieval", "token", "complete"]
    data: dict[str, Any]
