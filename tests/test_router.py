import pytest

from rag_framework.core.models import Query, QueryType, RetrievalStrategy
from rag_framework.providers.router import HeuristicQueryRouter


@pytest.mark.asyncio
async def test_router_uses_filters_for_filtered_search() -> None:
    plan = await HeuristicQueryRouter().plan(Query(text="Show policy documents", filters={"team": "legal"}))

    assert plan.query_type == QueryType.FILTERED_SEARCH
    assert plan.filters == {"team": "legal"}


@pytest.mark.asyncio
async def test_router_expands_conversational_reference() -> None:
    plan = await HeuristicQueryRouter().plan(
        Query(text="What does it require?", history=["Explain the security policy"])
    )

    assert plan.query_type == QueryType.CONVERSATION_FOLLOWUP
    assert plan.rewrite_required is True
    assert plan.rewritten_queries


@pytest.mark.asyncio
async def test_router_uses_hybrid_for_short_fact_lookup() -> None:
    plan = await HeuristicQueryRouter().plan(Query(text="RRF algorithm"))

    assert plan.query_type == QueryType.FACT_LOOKUP
    assert plan.strategy == RetrievalStrategy.HYBRID
