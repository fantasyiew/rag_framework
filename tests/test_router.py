import pytest

from rag_framework.core.models import Query, QueryType
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
