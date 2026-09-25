"""Framework-wide value objects with no domain or provider dependency."""

from __future__ import annotations

from enum import Enum
from time import time
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    FACT_LOOKUP = "fact_lookup"
    SEMANTIC_QUESTION = "semantic_question"
    FILTERED_SEARCH = "filtered_search"
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


class RetrievalPlan(BaseModel):
    query_type: QueryType
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    top_k: int = Field(default=8, ge=1, le=100)
    rerank: bool = True
    rewrite_required: bool = False
    rewritten_queries: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    source: str
    rank: int = Field(ge=1)
    component_scores: dict[str, float] = Field(default_factory=dict)


class TraceStep(BaseModel):
    name: str
    duration_ms: float = Field(ge=0)
    details: dict[str, Any] = Field(default_factory=dict)


class RetrievalTrace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    query: Query
    plan: RetrievalPlan | None = None
    candidates: list[RetrievedChunk] = Field(default_factory=list)
    final_context: list[RetrievedChunk] = Field(default_factory=list)
    steps: list[TraceStep] = Field(default_factory=list)
    started_at: float = Field(default_factory=time)

    def add_step(self, name: str, duration_ms: float, **details: Any) -> None:
        self.steps.append(TraceStep(name=name, duration_ms=duration_ms, details=details))
