import pytest

from rag_framework.contracts.providers import StructuredOutputLLM
from rag_framework.core.models import Query, QueryType, RetrievalStrategy
from rag_framework.providers.router import HeuristicQueryPlanner, LLMQueryPlanner


class StubLLM(StructuredOutputLLM):
    def __init__(self, payload: dict[str, object] | Exception) -> None:
        self.payload = payload

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


@pytest.mark.asyncio
async def test_router_uses_filters_for_filtered_search() -> None:
    plan = await HeuristicQueryPlanner().plan(
        Query(text="Show policy documents", filters={"team": "legal"})
    )

    assert plan.query_type == QueryType.FILTERED_SEARCH
    assert plan.filters == {"team": "legal"}


@pytest.mark.asyncio
async def test_router_expands_conversational_reference() -> None:
    plan = await HeuristicQueryPlanner().plan(
        Query(text="What does it require?", history=["Explain the security policy"])
    )

    assert plan.query_type == QueryType.CONVERSATION_FOLLOWUP
    assert plan.rewrite_required is True
    assert plan.rewritten_queries


@pytest.mark.asyncio
async def test_router_uses_hybrid_for_short_fact_lookup() -> None:
    plan = await HeuristicQueryPlanner().plan(Query(text="RRF algorithm"))

    assert plan.query_type == QueryType.FACT_LOOKUP
    assert plan.strategy == RetrievalStrategy.HYBRID


@pytest.mark.asyncio
async def test_planner_uses_keyword_for_exact_identifier() -> None:
    plan = await HeuristicQueryPlanner().plan(Query(text="查找错误码 API-404"))

    assert plan.query_type == QueryType.EXACT_MATCH
    assert plan.strategy == RetrievalStrategy.KEYWORD
    assert plan.planner == "heuristic"


@pytest.mark.asyncio
async def test_llm_planner_normalizes_rewrites_and_preserves_caller_filters() -> None:
    planner = LLMQueryPlanner(
        StubLLM(
            {
                "analysis": {
                    "query_type": "semantic_question",
                    "normalized_query": "RAG retrieval",
                    "rewrite_required": True,
                    "rewritten_queries": [
                        "RAG retrieval",
                        "  vector retrieval  ",
                        "vector retrieval",
                    ],
                    "keywords": ["rag"],
                    "filters": {"team": "model", "locale": "zh"},
                    "reason": "Semantic query",
                    "confidence": 0.9,
                },
                "decision": {
                    "strategy": "vector",
                    "top_k": 6,
                    "rerank": True,
                    "reason": "Semantic evidence",
                    "confidence": 0.9,
                },
            }
        )
    )

    plan = await planner.plan(Query(text="RAG retrieval", filters={"team": "user"}))

    assert plan.planner == "llm"
    assert plan.rewritten_queries == ["vector retrieval"]
    assert plan.filters == {"team": "user", "locale": "zh"}
    assert plan.strategy == RetrievalStrategy.VECTOR


@pytest.mark.asyncio
async def test_llm_planner_uses_hybrid_when_confidence_is_low() -> None:
    planner = LLMQueryPlanner(
        StubLLM(
            {
                "query_type": "ambiguous",
                "normalized_query": "something",
                "strategy": "keyword",
                "confidence": 0.2,
            }
        )
    )

    plan = await planner.plan(Query(text="something"))

    assert plan.strategy == RetrievalStrategy.HYBRID
    assert plan.fallback_used is True
    assert plan.planner == "llm_safety_fallback"


@pytest.mark.asyncio
async def test_llm_planner_falls_back_when_provider_fails() -> None:
    plan = await LLMQueryPlanner(StubLLM(RuntimeError("unavailable"))).plan(
        Query(text="RRF algorithm")
    )

    assert plan.strategy == RetrievalStrategy.HYBRID
    assert plan.fallback_used is True
    assert plan.planner == "heuristic_fallback"
    assert "RuntimeError" in (plan.fallback_reason or "")
