"""FastAPI entry point for indexing and observable adaptive retrieval."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi import Query as QueryParameter
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rag_framework.config import settings
from rag_framework.core.models import Document, Query, RAGResponse, RetrievalPlan, RetrievalTrace
from rag_framework.evaluation import (
    AnyEvaluationReportSummary,
    DatasetEvaluationRequest,
    DatasetFormatError,
    EvaluationDataset,
    EvaluationDatasetSummary,
    EvaluationReport,
    RAGEvaluationReport,
    RAGEvaluationRequest,
    RetrievalEvaluationReport,
    RetrievalEvaluationRequest,
)
from rag_framework.index_state import IndexCompatibilityError
from rag_framework.knowledge_bases import knowledge_base_router
from rag_framework.service import build_service
from rag_framework.sources.api import source_router


class IndexDocumentsRequest(BaseModel):
    documents: list[Document] = Field(min_length=1)
    knowledge_base_id: str = Field(default="default", min_length=1, max_length=64)


class IndexDocumentsResponse(BaseModel):
    indexed_documents: int
    indexed_chunks: int


service = build_service(settings)
knowledge_bases = service.knowledge_bases
default_runtime = knowledge_bases.runtime("default")
keyword_store = default_runtime.keyword_store
default_source_service = default_runtime.sources
planner_runtime = service.planner_runtime
generator_runtime = service.generator_runtime
judge_runtime = service.judge_runtime
reranker = service.reranker
evaluation_store = service.evaluation_store
evaluation_dataset_store = service.evaluation_dataset_store
retrieval_evaluator = service.retrieval_evaluator()
rag_evaluator = service.rag_evaluator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep management endpoints available so blocked legacy indexes can be rebuilt.
    app.state.index_checks = {
        item.id: await knowledge_bases.runtime(item.id).index_state.describe()
        for item in knowledge_bases.list()
    }
    yield
    await service.close()

app = FastAPI(
    title="RAG Framework API",
    description="Provider-agnostic RAG control plane with adaptive retrieval traces.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(IndexCompatibilityError)
async def index_compatibility_error(request: Request, exc: IndexCompatibilityError):
    return JSONResponse(status_code=409, content={"detail": str(exc), "code": "index_incompatible"})


@app.get("/health")
async def health() -> dict[str, Any]:
    health_check = getattr(keyword_store, "health", None)
    primary_healthy = bool(await health_check()) if health_check is not None else True
    index_status = await default_runtime.index_state.describe()
    return {
        "components": {name: asdict(info) for name, info in service.components.items()},
        "status": "healthy" if primary_healthy and index_status["status"] in {"ready", "empty"} else "degraded",
        "index": index_status,
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
    try:
        pipeline = knowledge_bases.runtime(request.knowledge_base_id).indexing_pipeline
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge base not found") from exc
    chunks = await pipeline.index(request.documents)
    return IndexDocumentsResponse(indexed_documents=len(request.documents), indexed_chunks=len(chunks))


@app.post("/v1/retrieve", response_model=RetrievalTrace)
async def retrieve(query: Query) -> RetrievalTrace:
    try:
        runtime = knowledge_bases.runtime(query.knowledge_base_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge base not found") from exc
    return await runtime.retriever.retrieve(query)


@app.post("/v1/evaluations/retrieval", response_model=RetrievalEvaluationReport)
async def evaluate_retrieval(
    request: RetrievalEvaluationRequest,
) -> RetrievalEvaluationReport:
    """Run a labelled retrieval dataset through the active retrieval pipeline."""

    try:
        knowledge_bases.get(request.knowledge_base_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge base not found") from exc
    evaluator = retrieval_evaluator if request.knowledge_base_id == "default" else service.retrieval_evaluator(request.knowledge_base_id)
    return await evaluator.evaluate(request)


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
    try:
        knowledge_bases.get(request.knowledge_base_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge base not found") from exc
    evaluator = retrieval_evaluator if request.knowledge_base_id == "default" else service.retrieval_evaluator(request.knowledge_base_id)
    return await evaluator.evaluate(
        RetrievalEvaluationRequest(
            cases=dataset.cases,
            knowledge_base_id=request.knowledge_base_id,
            k=request.k,
            include_trace=request.include_trace,
            dataset_id=dataset.id,
        )
    )


@app.post("/v1/evaluations/rag", response_model=RAGEvaluationReport)
async def evaluate_rag(request: RAGEvaluationRequest) -> RAGEvaluationReport:
    """Run retrieval and answer generation, then score both stages."""

    try:
        knowledge_bases.get(request.knowledge_base_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge base not found") from exc
    evaluator = rag_evaluator if request.knowledge_base_id == "default" else service.rag_evaluator(request.knowledge_base_id)
    return await evaluator.evaluate(request)


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
    try:
        knowledge_bases.get(request.knowledge_base_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge base not found") from exc
    evaluator = rag_evaluator if request.knowledge_base_id == "default" else service.rag_evaluator(request.knowledge_base_id)
    return await evaluator.evaluate(
        RAGEvaluationRequest(
            cases=dataset.cases,
            knowledge_base_id=request.knowledge_base_id,
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
    try:
        runtime = knowledge_bases.runtime(query.knowledge_base_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge base not found") from exc
    return await runtime.generation_pipeline.run(query)


@app.post("/v1/chat/stream")
async def stream_chat(query: Query) -> StreamingResponse:
    try:
        runtime = knowledge_bases.runtime(query.knowledge_base_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Knowledge base not found") from exc

    await runtime.indexing_pipeline.check_index()

    async def events():
        try:
            async for event in runtime.generation_pipeline.stream(query):
                payload = json.dumps(event.data, ensure_ascii=False, default=str)
                yield f"event: {event.type}\ndata: {payload}\n\n"
        except Exception as exc:  # noqa: BLE001 - Convert provider failure to a terminal SSE event.
            payload = json.dumps(
                {"error": type(exc).__name__, "message": "Answer generation failed."}
            )
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


app.include_router(source_router(default_source_service))
app.include_router(knowledge_base_router(knowledge_bases))

# Registered last so the console never shadows API routes.
app.mount("/", StaticFiles(directory=Path(__file__).parents[1] / "web", html=True), name="console")
