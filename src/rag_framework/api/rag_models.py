"""Stable local, non-streaming RAG service contract."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rag_framework.core.models import Citation, RetrievedChunk, RetrievalTrace


class RAGRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1)
    knowledge_base_id: str = Field(default='default', min_length=1, max_length=64)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    history: list[str] = Field(default_factory=list)
    include_trace: bool = False


class GenerationResult(BaseModel):
    model: str
    fallback_used: bool
    status: Literal['completed', 'fallback', 'no_context', 'empty_answer']


class RAGServiceResponse(BaseModel):
    request_id: str
    conversation_id: str | None
    knowledge_base_id: str
    answer: str
    generation: GenerationResult
    citations: list[Citation]
    contexts: list[RetrievedChunk]
    trace_id: str
    config_version: int
    config_hash: str
    duration_ms: float
    trace: RetrievalTrace | None = None
