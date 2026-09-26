"""FastAPI entry point for indexing and observable adaptive retrieval."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi import Query as QueryParameter
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from rag_framework.config import settings
from rag_framework.core.models import Document, Query, RAGResponse, RetrievalPlan, RetrievalTrace
from rag_framework.evaluation import (
    AnyEvaluationReportSummary,
    DatasetEvaluationRequest,
    DatasetFormatError,
    EvaluationDataset,
    EvaluationDatasetStore,
    EvaluationDatasetSummary,
    EvaluationReport,
    EvaluationStore,
    RAGEvaluationReport,
    RAGEvaluationRequest,
    RAGEvaluator,
    RetrievalEvaluationReport,
    RetrievalEvaluationRequest,
    RetrievalEvaluator,
)
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.pipeline.indexing import CharacterChunker, IndexingPipeline
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers import (
    ChromaVectorStore,
    HashEmbedder,
    build_answer_generator,
    build_answer_judge,
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
judge_runtime = build_answer_judge(settings)
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
evaluation_store = EvaluationStore(
    limit=settings.evaluation_report_limit,
    directory=settings.evaluation_report_directory,
)
evaluation_dataset_store = EvaluationDatasetStore(
    settings.evaluation_dataset_directory,
    max_cases=settings.evaluation_dataset_max_cases,
)
retrieval_evaluator = RetrievalEvaluator(
    retriever,
    evaluation_store,
    concurrency=settings.evaluation_concurrency,
)
rag_evaluator = RAGEvaluator(
    generation_pipeline,
    evaluation_store,
    concurrency=settings.evaluation_concurrency,
    judge=judge_runtime.judge,
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
        "configured_evaluation_judge_mode": judge_runtime.configured_mode,
        "active_evaluation_judge_mode": judge_runtime.active_mode,
        "evaluation_judge_provider": judge_runtime.provider,
        "evaluation_judge_model": judge_runtime.model,
        "evaluation_judge_fallback_reason": judge_runtime.fallback_reason,
    }


@app.post("/v1/index/documents", response_model=IndexDocumentsResponse)
async def index_documents(request: IndexDocumentsRequest) -> IndexDocumentsResponse:
    chunks = await indexing_pipeline.index(request.documents)
    return IndexDocumentsResponse(indexed_documents=len(request.documents), indexed_chunks=len(chunks))


@app.post("/v1/retrieve", response_model=RetrievalTrace)
async def retrieve(query: Query) -> RetrievalTrace:
    return await retriever.retrieve(query)


@app.post("/v1/evaluations/retrieval", response_model=RetrievalEvaluationReport)
async def evaluate_retrieval(
    request: RetrievalEvaluationRequest,
) -> RetrievalEvaluationReport:
    """Run a labelled retrieval dataset through the active retrieval pipeline."""

    return await retrieval_evaluator.evaluate(request)


@app.post(
    "/v1/evaluations/retrieval/datasets/{dataset_id}",
    response_model=RetrievalEvaluationReport,
)
async def evaluate_retrieval_dataset(
    dataset_id: str,
    request: DatasetEvaluationRequest,
) -> RetrievalEvaluationReport:
    dataset = evaluation_dataset_store.get(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Evaluation dataset not found")
    return await retrieval_evaluator.evaluate(
        RetrievalEvaluationRequest(
            cases=dataset.cases,
            k=request.k,
            include_trace=request.include_trace,
            dataset_id=dataset.id,
        )
    )


@app.post("/v1/evaluations/rag", response_model=RAGEvaluationReport)
async def evaluate_rag(request: RAGEvaluationRequest) -> RAGEvaluationReport:
    """Run retrieval and answer generation, then score both stages."""

    return await rag_evaluator.evaluate(request)


@app.post(
    "/v1/evaluations/rag/datasets/{dataset_id}",
    response_model=RAGEvaluationReport,
)
async def evaluate_rag_dataset(
    dataset_id: str,
    request: DatasetEvaluationRequest,
) -> RAGEvaluationReport:
    dataset = evaluation_dataset_store.get(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Evaluation dataset not found")
    return await rag_evaluator.evaluate(
        RAGEvaluationRequest(
            cases=dataset.cases,
            k=request.k,
            include_trace=request.include_trace,
            dataset_id=dataset.id,
        )
    )


@app.get("/v1/evaluations", response_model=list[AnyEvaluationReportSummary])
async def list_evaluations() -> list[AnyEvaluationReportSummary]:
    return evaluation_store.list()


@app.get("/v1/evaluations/{report_id}", response_model=EvaluationReport)
async def get_evaluation(report_id: str) -> EvaluationReport:
    report = evaluation_store.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Evaluation report not found")
    return report


@app.post("/v1/evaluation-datasets/import", response_model=EvaluationDataset)
async def import_evaluation_dataset(
    request: Request,
    name: str = QueryParameter(min_length=1, max_length=200),
    description: str | None = QueryParameter(default=None, max_length=2000),
) -> EvaluationDataset:
    content = await request.body()
    if len(content) > settings.evaluation_dataset_max_bytes:
        raise HTTPException(status_code=413, detail="Evaluation dataset is too large")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Dataset must be UTF-8 encoded") from exc
    try:
        return evaluation_dataset_store.import_jsonl(
            text,
            name=name,
            description=description,
        )
    except DatasetFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/evaluation-datasets", response_model=list[EvaluationDatasetSummary])
async def list_evaluation_datasets() -> list[EvaluationDatasetSummary]:
    return evaluation_dataset_store.list()


@app.get("/v1/evaluation-datasets/{dataset_id}", response_model=EvaluationDataset)
async def get_evaluation_dataset(dataset_id: str) -> EvaluationDataset:
    dataset = evaluation_dataset_store.get(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Evaluation dataset not found")
    return dataset


@app.get("/v1/evaluation-datasets/{dataset_id}/export")
async def export_evaluation_dataset(dataset_id: str) -> Response:
    content = evaluation_dataset_store.export_jsonl(dataset_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Evaluation dataset not found")
    return Response(
        content=content,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="evaluation-{dataset_id}.jsonl"'
        },
    )


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
