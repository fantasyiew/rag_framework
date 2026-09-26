import os

import pytest

from rag_framework.config import settings
from rag_framework.core.models import (
    Chunk,
    GeneratedAnswer,
    Query,
    RAGResponse,
    RetrievalTrace,
    RetrievedChunk,
)
from rag_framework.evaluation import EvaluationCase
from rag_framework.providers.judge_factory import build_answer_judge


@pytest.mark.integration
@pytest.mark.asyncio
async def test_configured_llm_judge_returns_structured_scores() -> None:
    if os.getenv("RAG_RUN_LIVE_JUDGE") != "1":
        pytest.skip("Set RAG_RUN_LIVE_JUDGE=1 to run the configured LLM judge")
    if not (
        settings.evaluation_judge_api_key
        or settings.generation_api_key
        or settings.planner_api_key
    ):
        pytest.skip("No evaluation, generation, or planner API key configured")
    pytest.importorskip("langchain_openai")

    runtime = build_answer_judge(
        settings.model_copy(update={"evaluation_judge_mode": "llm"})
    )
    query = Query(text="How tall is Tokyo Tower?")
    context = RetrievedChunk(
        chunk=Chunk(
            id="tokyo-tower",
            document_id="tokyo",
            index=0,
            content="Tokyo Tower is 333 meters tall.",
        ),
        score=1,
        source="integration",
        rank=1,
    )
    trace = RetrievalTrace(query=query, candidates=[context], final_context=[context])
    trace.add_step("generate_answer", 1, context_count=1)
    response = RAGResponse(
        retrieval=trace,
        answer=GeneratedAnswer(
            text="Tokyo Tower is 333 meters tall [1].",
            model="fixture",
        ),
    )
    case = EvaluationCase(
        query=query,
        relevant_chunk_ids=["tokyo-tower"],
        reference_answer="Tokyo Tower is 333 meters tall.",
    )

    metrics = await runtime.judge.evaluate(case, response)

    assert metrics.method == "llm_judge_v1"
    assert metrics.fallback_used is False
    assert metrics.judge_rationale
