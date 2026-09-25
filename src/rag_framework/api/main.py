"""FastAPI entry point for indexing and observable adaptive retrieval."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from rag_framework.config import settings
from rag_framework.core.models import Document, Query, RAGResponse, RetrievalPlan, RetrievalTrace
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.pipeline.indexing import CharacterChunker, IndexingPipeline
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers import (
    ChromaVectorStore,
    HashEmbedder,
    build_answer_generator,
    build_query_planner,
    build_reranker,
    create_keyword_store,
)


class IndexDocumentsRequest(BaseModel):
    documents: list[Document] = Field(min_length=1)


class IndexDocumentsResponse(BaseModel):
    indexed_documents: int
    indexed_chunks: int


vector_store = ChromaVectorStore(settings.chroma_directory, settings.chroma_collection)
keyword_store = create_keyword_store(settings)
embedder = HashEmbedder(settings.embedding_dimensions)
planner_runtime = build_query_planner(settings)
generator_runtime = build_answer_generator(settings)
reranker = build_reranker(settings)
indexing_pipeline = IndexingPipeline(CharacterChunker(), embedder, vector_store, keyword_store)
retriever = AdaptiveRetriever(
    vector_store,
    embedder,
    planner_runtime.planner,
    keyword_store,
    reranker=reranker,
    reranker_candidate_k=settings.reranker_candidate_k,
    reranker_fail_open=settings.reranker_mode == "auto",
    hybrid_candidate_multiplier=settings.hybrid_candidate_multiplier,
    rrf_rank_constant=settings.rrf_rank_constant,
)
generation_pipeline = GenerationPipeline(
    retriever,
    generator_runtime.generator,
    max_context_chunks=settings.generation_max_context_chunks,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close = getattr(keyword_store, "close", None)
    if close is not None:
        await close()
    close_reranker = getattr(reranker, "close", None)
    if close_reranker is not None:
        await close_reranker()

app = FastAPI(
    title="RAG Framework API",
    description="Provider-agnostic RAG control plane with adaptive retrieval traces.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    health_check = getattr(keyword_store, "health", None)
    primary_healthy = bool(await health_check()) if health_check is not None else True
    return {
        "status": "healthy" if primary_healthy else "degraded",
        "configured_keyword_backend": settings.keyword_backend,
        "active_keyword_store": type(keyword_store).__name__,
        "keyword_primary_healthy": primary_healthy,
        "reranker_mode": settings.reranker_mode,
        "reranker_model": getattr(reranker, "model_name", None),
        "reranker_provider": type(reranker).__name__ if reranker else None,
        "reranker_loading": (
            "lazy" if type(reranker).__name__ == "CrossEncoderReranker" else
            "remote" if reranker else "disabled"
        ),
        "configured_query_planner_mode": planner_runtime.configured_mode,
        "active_query_planner_mode": planner_runtime.active_mode,
        "query_planner_provider": planner_runtime.provider,
        "query_planner_model": (
            settings.planner_model if planner_runtime.active_mode == "llm" else None
        ),
        "query_planner_fallback_reason": planner_runtime.fallback_reason,
        "configured_answer_generator_mode": generator_runtime.configured_mode,
        "active_answer_generator_mode": generator_runtime.active_mode,
        "answer_generator_provider": generator_runtime.provider,
        "answer_generator_model": generator_runtime.model,
        "answer_generator_fallback_reason": generator_runtime.fallback_reason,
    }


@app.post("/v1/index/documents", response_model=IndexDocumentsResponse)
async def index_documents(request: IndexDocumentsRequest) -> IndexDocumentsResponse:
    chunks = await indexing_pipeline.index(request.documents)
    return IndexDocumentsResponse(indexed_documents=len(request.documents), indexed_chunks=len(chunks))


@app.post("/v1/retrieve", response_model=RetrievalTrace)
async def retrieve(query: Query) -> RetrievalTrace:
    return await retriever.retrieve(query)


@app.post("/v1/query/plan", response_model=RetrievalPlan)
async def plan_query(query: Query) -> RetrievalPlan:
    """Inspect query analysis and strategy selection without running retrieval."""

    return await planner_runtime.planner.plan(query)


@app.post("/v1/chat", response_model=RAGResponse)
async def chat(query: Query) -> RAGResponse:
    return await generation_pipeline.run(query)


@app.post("/v1/chat/stream")
async def stream_chat(query: Query) -> StreamingResponse:
    async def events():
        try:
            async for event in generation_pipeline.stream(query):
                payload = json.dumps(event.data, ensure_ascii=False, default=str)
                yield f"event: {event.type}\ndata: {payload}\n\n"
        except Exception as exc:  # noqa: BLE001 - Convert provider failure to a terminal SSE event.
            payload = json.dumps(
                {"error": type(exc).__name__, "message": "Answer generation failed."}
            )
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
