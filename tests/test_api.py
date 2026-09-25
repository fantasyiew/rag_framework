from types import SimpleNamespace

import pytest

from rag_framework.api import main
from rag_framework.core.models import Query, QueryType, RetrievalStrategy
from rag_framework.providers.router import HeuristicQueryPlanner


@pytest.mark.asyncio
async def test_plan_endpoint_returns_structured_analysis_and_decision(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "planner_runtime",
        SimpleNamespace(planner=HeuristicQueryPlanner()),
    )
    plan = await main.plan_query(Query(text="查找错误码 API-404"))

    assert plan.analysis.query_type == QueryType.EXACT_MATCH
    assert plan.decision.strategy == RetrievalStrategy.KEYWORD


@pytest.mark.asyncio
async def test_health_exposes_active_planner_without_secrets() -> None:
    payload = await main.health()

    assert payload["configured_query_planner_mode"] in {"heuristic", "llm", "auto"}
    assert payload["active_query_planner_mode"] in {"heuristic", "llm"}
    assert "api_key" not in payload
