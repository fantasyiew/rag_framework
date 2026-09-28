"""Fixed retrieval plan without query analysis or model calls."""

from rag_framework.contracts.providers import QueryPlanner
from rag_framework.core.models import (
    Query,
    QueryAnalysis,
    QueryType,
    RetrievalDecision,
    RetrievalPlan,
    RetrievalStrategy,
)


class FixedQueryPlanner(QueryPlanner):
    def __init__(self, strategy: str, top_k: int, rerank: bool):
        self.strategy = RetrievalStrategy(strategy)
        self.top_k = top_k
        self.rerank = rerank

    async def plan(self, query: Query) -> RetrievalPlan:
        reason = "Planner disabled; fixed strategy, no analysis or rewrite."
        return RetrievalPlan(
            analysis=QueryAnalysis(
                query_type=QueryType.AMBIGUOUS, normalized_query=query.text,
                filters=query.filters, reason=reason,
            ),
            decision=RetrievalDecision(
                strategy=self.strategy, top_k=self.top_k, rerank=self.rerank, reason=reason,
            ),
            planner="disabled",
        )
