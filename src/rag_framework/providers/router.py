"""Provider-neutral query planners with deterministic safety fallbacks."""

from __future__ import annotations

import re

from rag_framework.contracts.providers import QueryPlanner, StructuredOutputLLM
from rag_framework.core.models import (
    Query,
    QueryAnalysis,
    QueryType,
    RetrievalDecision,
    RetrievalPlan,
    RetrievalStrategy,
)

_FOLLOWUP_PATTERN = re.compile(
    r"(?:\b(?:it|that|they|this|those|former|latter)\b|它|这个|上述|前者|后者)",
    re.IGNORECASE,
)
_COMPARISON_PATTERN = re.compile(
    r"(?:\b(?:compare|versus|vs\.?|difference|better than)\b|对比|比较|区别|差异|哪个好)",
    re.IGNORECASE,
)
_MULTI_HOP_PATTERN = re.compile(
    r"(?:\b(?:relationship between|based on .* then|first .* then)\b|分别.*并|先.*再|根据.*推断)",
    re.IGNORECASE,
)
_EXACT_PATTERN = re.compile(
    r"(?:[\"“][^\"”]+[\"”]|\b[A-Z]{2,}[-_:]\d+[A-Z0-9_-]*\b|错误码|编号|\bID\b)",
    re.IGNORECASE,
)
_KEYWORD_PATTERN = re.compile(r"[A-Za-z0-9_.:+-]+|[\u3400-\u9fff]{2,}")


def _keywords(text: str, *, limit: int = 8) -> list[str]:
    return list(dict.fromkeys(match.group(0).lower() for match in _KEYWORD_PATTERN.finditer(text)))[:limit]


def _is_short_query(text: str) -> bool:
    latin_tokens = re.findall(r"[A-Za-z0-9]+", text)
    cjk_characters = re.findall(r"[\u3400-\u9fff]", text)
    return len(latin_tokens) <= 5 and len(cjk_characters) <= 12


class HeuristicQueryPlanner(QueryPlanner):
    """Fast deterministic planner used by default and as the LLM safety net."""

    def __init__(self, *, default_top_k: int = 8) -> None:
        self.default_top_k = default_top_k

    async def plan(self, query: Query) -> RetrievalPlan:
        text = " ".join(query.text.split())
        keywords = _keywords(text)

        if query.history and _FOLLOWUP_PATTERN.search(text):
            standalone = f"{query.history[-1].strip()} {text}".strip()
            return self._build(
                query=query,
                query_type=QueryType.CONVERSATION_FOLLOWUP,
                strategy=RetrievalStrategy.HYBRID,
                reason="Query contains a conversational reference and needs standalone context.",
                confidence=0.85,
                keywords=keywords,
                rewritten_queries=[standalone],
            )

        if query.filters:
            return self._build(
                query=query,
                query_type=QueryType.FILTERED_SEARCH,
                strategy=RetrievalStrategy.HYBRID,
                reason="Caller supplied metadata filters; hybrid retrieval preserves exact and semantic evidence.",
                confidence=0.95,
                keywords=keywords,
            )

        if _EXACT_PATTERN.search(text):
            return self._build(
                query=query,
                query_type=QueryType.EXACT_MATCH,
                strategy=RetrievalStrategy.KEYWORD,
                reason="Query contains a quoted phrase or identifier suited to lexical retrieval.",
                confidence=0.88,
                keywords=keywords,
            )

        if _COMPARISON_PATTERN.search(text):
            return self._build(
                query=query,
                query_type=QueryType.COMPARISON,
                strategy=RetrievalStrategy.HYBRID,
                reason="Comparison queries benefit from semantic and lexical evidence for every subject.",
                confidence=0.82,
                keywords=keywords,
            )

        if _MULTI_HOP_PATTERN.search(text):
            return self._build(
                query=query,
                query_type=QueryType.MULTI_HOP,
                strategy=RetrievalStrategy.HYBRID,
                reason="Multi-step query needs broad evidence before downstream synthesis.",
                confidence=0.75,
                keywords=keywords,
            )

        if _is_short_query(text):
            return self._build(
                query=query,
                query_type=QueryType.FACT_LOOKUP,
                strategy=RetrievalStrategy.HYBRID,
                reason="Short entity-oriented query benefits from semantic and lexical recall.",
                confidence=0.7,
                keywords=keywords,
            )

        return self._build(
            query=query,
            query_type=QueryType.SEMANTIC_QUESTION,
            strategy=RetrievalStrategy.VECTOR,
            reason="Natural-language question is best served by semantic retrieval.",
            confidence=0.68,
            keywords=keywords,
        )

    def _build(
        self,
        *,
        query: Query,
        query_type: QueryType,
        strategy: RetrievalStrategy,
        reason: str,
        confidence: float,
        keywords: list[str],
        rewritten_queries: list[str] | None = None,
    ) -> RetrievalPlan:
        rewrites = rewritten_queries or []
        return RetrievalPlan(
            analysis=QueryAnalysis(
                query_type=query_type,
                normalized_query=" ".join(query.text.split()),
                rewrite_required=bool(rewrites),
                rewritten_queries=rewrites,
                keywords=keywords,
                filters=query.filters,
                reason=reason,
                confidence=confidence,
            ),
            decision=RetrievalDecision(
                strategy=strategy,
                top_k=self.default_top_k,
                rerank=True,
                reason=reason,
                confidence=confidence,
            ),
            planner="heuristic",
        )


class LLMQueryPlanner(QueryPlanner):
    """Uses structured LLM output while enforcing safe, observable fallback behavior."""

    _SYSTEM_PROMPT = """You are a RAG query planner. Return JSON matching this schema:
analysis: query_type (exact_match|fact_lookup|semantic_question|filtered_search|comparison|
multi_hop|conversation_followup|ambiguous), normalized_query, rewrite_required,
rewritten_queries (0-4 standalone queries), keywords, filters, reason, confidence (0-1);
decision: strategy (vector|keyword|hybrid), top_k (1-100), rerank, reason, confidence (0-1).
Preserve user meaning and explicit filters. Rewrites supplement rather than replace the original.
Prefer hybrid when uncertain. Do not answer the query."""

    def __init__(
        self,
        llm: StructuredOutputLLM,
        fallback: QueryPlanner | None = None,
        *,
        minimum_confidence: float = 0.55,
        max_rewrites: int = 4,
    ) -> None:
        if not 0 <= minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between 0 and 1")
        if max_rewrites < 0:
            raise ValueError("max_rewrites must be non-negative")
        self.llm = llm
        self.fallback = fallback or HeuristicQueryPlanner()
        self.minimum_confidence = minimum_confidence
        self.max_rewrites = max_rewrites

    async def plan(self, query: Query) -> RetrievalPlan:
        try:
            payload = await self.llm.complete_json(
                system_prompt=self._SYSTEM_PROMPT,
                user_prompt=query.model_dump_json(),
            )
            plan = self._normalize_plan(RetrievalPlan.model_validate(payload), query)
        except Exception as exc:  # noqa: BLE001 - Provider failures must not block retrieval.
            return await self._fallback(query, f"LLM planning failed: {type(exc).__name__}")

        confidence = min(plan.analysis.confidence, plan.decision.confidence)
        if confidence < self.minimum_confidence or plan.query_type == QueryType.AMBIGUOUS:
            return self._uncertain_hybrid_plan(
                plan,
                f"LLM confidence {confidence:.2f} is below threshold {self.minimum_confidence:.2f}.",
            )
        return plan.model_copy(update={"planner": "llm"})

    def _normalize_plan(self, plan: RetrievalPlan, query: Query) -> RetrievalPlan:
        original = " ".join(query.text.split())
        rewrites = []
        seen = {original.casefold()}
        for candidate in plan.analysis.rewritten_queries:
            normalized = " ".join(candidate.split())
            if normalized and normalized.casefold() not in seen:
                seen.add(normalized.casefold())
                rewrites.append(normalized)
            if len(rewrites) >= self.max_rewrites:
                break

        analysis = plan.analysis.model_copy(
            update={
                "normalized_query": original
                if plan.analysis.normalized_query == "unknown"
                else " ".join(plan.analysis.normalized_query.split()),
                "rewrite_required": bool(rewrites),
                "rewritten_queries": rewrites,
                "filters": {**plan.analysis.filters, **query.filters},
            }
        )
        return plan.model_copy(update={"analysis": analysis, "planner": "llm"})

    async def _fallback(self, query: Query, reason: str) -> RetrievalPlan:
        plan = await self.fallback.plan(query)
        return plan.model_copy(
            update={
                "planner": "heuristic_fallback",
                "fallback_used": True,
                "fallback_reason": reason,
            }
        )

    @staticmethod
    def _uncertain_hybrid_plan(plan: RetrievalPlan, reason: str) -> RetrievalPlan:
        decision = plan.decision.model_copy(
            update={
                "strategy": RetrievalStrategy.HYBRID,
                "reason": reason,
            }
        )
        return plan.model_copy(
            update={
                "decision": decision,
                "planner": "llm_safety_fallback",
                "fallback_used": True,
                "fallback_reason": reason,
            }
        )


# Compatibility aliases retained for callers using the original router terminology.
HeuristicQueryRouter = HeuristicQueryPlanner
LLMQueryRouter = LLMQueryPlanner
