"""Deterministic fallback router. An LLM router can implement the same port."""

from __future__ import annotations

import re

from rag_framework.contracts.providers import QueryRouter, StructuredOutputLLM
from rag_framework.core.models import Query, QueryType, RetrievalPlan, RetrievalStrategy


class HeuristicQueryRouter(QueryRouter):
    async def plan(self, query: Query) -> RetrievalPlan:
        text = query.text.strip()
        if query.history and re.search(r"\b(it|that|they|它|这个|上述)\b", text, re.IGNORECASE):
            return RetrievalPlan(
                query_type=QueryType.CONVERSATION_FOLLOWUP,
                rewrite_required=True,
                rewritten_queries=[f"{query.history[-1]} {text}"],
                reason="Query contains a conversational reference.",
                confidence=0.8,
            )
        if query.filters:
            return RetrievalPlan(
                query_type=QueryType.FILTERED_SEARCH,
                filters=query.filters,
                strategy=RetrievalStrategy.HYBRID,
                reason="Caller provided metadata filters.",
                confidence=0.95,
            )
        if len(text.split()) <= 5:
            return RetrievalPlan(
                query_type=QueryType.FACT_LOOKUP,
                strategy=RetrievalStrategy.HYBRID,
                rewrite_required=False,
                reason="Short entity-oriented query.",
                confidence=0.65,
            )
        return RetrievalPlan(
            query_type=QueryType.SEMANTIC_QUESTION,
            strategy=RetrievalStrategy.VECTOR,
            rewrite_required=False,
            reason="Natural-language question; semantic retrieval is the safe fallback.",
            confidence=0.6,
        )


class LLMQueryRouter(QueryRouter):
    """Routes with an LLM but never lets malformed output stop retrieval."""

    _SYSTEM_PROMPT = """You are a RAG query planner. Return JSON only with these fields:
query_type (fact_lookup|semantic_question|filtered_search|conversation_followup|ambiguous),
strategy (vector|keyword|hybrid), top_k (1-100), rerank (boolean), rewrite_required
(boolean), rewritten_queries (array of strings), filters (object), reason (string),
and confidence (0-1). Preserve the user's meaning. Rewrites supplement, never replace,
the original query."""

    def __init__(self, llm: StructuredOutputLLM, fallback: QueryRouter | None = None) -> None:
        self.llm = llm
        self.fallback = fallback or HeuristicQueryRouter()

    async def plan(self, query: Query) -> RetrievalPlan:
        try:
            payload = await self.llm.complete_json(
                system_prompt=self._SYSTEM_PROMPT,
                user_prompt=query.model_dump_json(),
            )
            return RetrievalPlan.model_validate(payload)
        except Exception:  # noqa: BLE001 - Provider failures must not block the fallback plan.
            return await self.fallback.plan(query)
