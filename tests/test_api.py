import pytest

from rag_framework.api.main import health, plan_query
from rag_framework.core.models import Query, QueryType, RetrievalStrategy


@pytest.mark.asyncio
async def test_plan_endpoint_returns_structured_analysis_and_decision() -> None:
    plan = await plan_query(Query(text="查找错误码 API-404"))

    assert plan.analysis.query_type == QueryType.EXACT_MATCH
    assert plan.decision.strategy == RetrievalStrategy.KEYWORD


@pytest.mark.asyncio
async def test_health_exposes_active_planner_without_secrets() -> None:
    payload = await health()

    assert payload["configured_query_planner_mode"] in {"heuristic", "llm", "auto"}
    assert payload["active_query_planner_mode"] in {"heuristic", "llm"}
    assert "api_key" not in payload
