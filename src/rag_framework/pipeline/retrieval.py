"""Adaptive retrieval orchestration with strategy execution and full decision trace."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterable
from time import perf_counter

from rag_framework.contracts.providers import (
    Embedder,
    Fusion,
    KeywordStore,
    QueryPlanner,
    Reranker,
    Retriever,
    VectorStore,
)
from rag_framework.core.models import (
    Query,
    RankChange,
    RerankComparison,
    RetrievalStrategy,
    RetrievalTrace,
    RetrievedChunk,
)
from rag_framework.pipeline.fusion import RRFFusion


class AdaptiveRetriever(Retriever):
    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        router: QueryPlanner,
        keyword_store: KeywordStore | None = None,
        reranker: Reranker | None = None,
        hybrid_candidate_multiplier: int = 2,
        rrf_rank_constant: int = 60,
        reranker_candidate_k: int = 32,
        reranker_fail_open: bool = True,
        fusion: Fusion | None = None,
    ) -> None:
        if hybrid_candidate_multiplier < 1:
            raise ValueError("hybrid_candidate_multiplier must be at least 1")
        if rrf_rank_constant < 0:
            raise ValueError("rrf_rank_constant must be non-negative")
        self.vector_store = vector_store
        self.embedder = embedder
        self.planner = router
        self.keyword_store = keyword_store
        self.reranker = reranker
        self.hybrid_candidate_multiplier = hybrid_candidate_multiplier
        self.rrf_rank_constant = rrf_rank_constant
        self.fusion = fusion if fusion is not None else RRFFusion(rrf_rank_constant)
        if reranker_candidate_k < 1:
            raise ValueError("reranker_candidate_k must be positive")
        self.reranker_candidate_k = reranker_candidate_k
        self.reranker_fail_open = reranker_fail_open

    async def retrieve(self, query: Query) -> RetrievalTrace:
        trace = RetrievalTrace(query=query)
        started = perf_counter()
        plan = await self.planner.plan(query)
        trace.plan = plan
        trace.add_step(
            "analyze_query",
            (perf_counter() - started) * 1000,
            analysis=plan.analysis.model_dump(),
            planner=plan.planner,
            skipped=plan.planner == "disabled",
            fallback_used=plan.fallback_used,
            fallback_reason=plan.fallback_reason,
        )

        retrieval_queries = (
            [query.text, *plan.rewritten_queries] if plan.rewrite_required else [query.text]
        )
        trace.retrieval_queries = list(dict.fromkeys(retrieval_queries))
        if plan.rewrite_required:
            trace.add_step(
                "rewrite_query",
                0,
                original_query=query.text,
                rewritten_queries=plan.rewritten_queries,
                effective_queries=trace.retrieval_queries,
            )
        trace.add_step(
            "select_retrieval_strategy",
            0,
            decision=plan.decision.model_dump(),
        )
        # Explicit caller filters are authoritative even when a custom planner proposes filters.
        from rag_framework.core.filters import document_filters
        proposed_filters = {**plan.filters, **query.filters}
        filters = document_filters(proposed_filters)
        if filters != proposed_filters:
            trace.add_step('sanitize_filters', 0,
                removed_fields=sorted(set(proposed_filters) - set(filters)), effective_filters=filters)
        candidates: dict[str, RetrievedChunk] = {}
        for retrieval_query in trace.retrieval_queries:
            results = await self._execute_strategy(
                strategy=plan.strategy,
                query=retrieval_query,
                top_k=(max(plan.top_k, self.reranker_candidate_k)
                       if self.reranker and plan.rerank else plan.top_k),
                filters=filters,
                trace=trace,
            )
            for result in results:
                previous = candidates.get(result.chunk.id)
                if previous is None or result.score > previous.score:
                    candidates[result.chunk.id] = result

        trace.candidates = self._rerank_positions(candidates.values())
        if self.reranker and plan.rerank:
            trace.candidates = trace.candidates[:max(plan.top_k, self.reranker_candidate_k)]
            rerank_started = perf_counter()
            model = getattr(self.reranker, "model_name", type(self.reranker).__name__)
            reason = None
            try:
                reranked = await self.reranker.rerank(
                    query.text, [item.model_copy(deep=True) for item in trace.candidates]
                )
                expected = {item.chunk.id for item in trace.candidates}
                if (len(reranked) != len(expected)
                        or {item.chunk.id for item in reranked} != expected
                        or any(not math.isfinite(item.score) for item in reranked)):
                    raise ValueError("Reranker must return every candidate once with finite scores")
            except Exception as exc:
                if not self.reranker_fail_open:
                    raise
                reason = type(exc).__name__
                reranked = trace.candidates
            # Provider order is authoritative; never re-sort by old recall scores.
            reranked = [item.model_copy(update={"rank": rank})
                        for rank, item in enumerate(reranked, 1)]
            trace.final_context = reranked[:plan.top_k]
            original = {item.chunk.id: item for item in trace.candidates}
            trace.rerank_comparison = RerankComparison(
                model=model, fallback_used=reason is not None, fallback_reason=reason,
                changes=[RankChange(
                    chunk_id=item.chunk.id, original_rank=original[item.chunk.id].rank,
                    final_rank=item.rank, original_score=original[item.chunk.id].score,
                    rerank_score=item.score if reason is None else None,
                ) for item in reranked],
            )
            trace.add_step(
                "rerank",
                (perf_counter() - rerank_started) * 1000,
                input_count=len(trace.candidates),
                output_count=len(trace.final_context),
                **trace.rerank_comparison.model_dump(),
            )
        else:
            trace.final_context = trace.candidates[: plan.top_k]
        return trace

    async def _execute_strategy(
        self,
        *,
        strategy: RetrievalStrategy,
        query: str,
        top_k: int,
        filters: dict[str, object],
        trace: RetrievalTrace,
    ) -> list[RetrievedChunk]:
        if strategy == RetrievalStrategy.KEYWORD:
            if self.keyword_store is None:
                return await self._fallback_to_vector(query, top_k, filters, trace, strategy)
            return await self._keyword_search(query, top_k, filters, trace)

        if strategy == RetrievalStrategy.HYBRID:
            if self.keyword_store is None:
                return await self._fallback_to_vector(query, top_k, filters, trace, strategy)
            return await self._hybrid_search(query, top_k, filters, trace)

        return await self._vector_search(query, top_k, filters, trace)

    async def _vector_search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, object],
        trace: RetrievalTrace,
    ) -> list[RetrievedChunk]:
        started = perf_counter()
        results = await self._vector_search_without_trace(query, top_k, filters)
        trace.add_step(
            "vector_search",
            (perf_counter() - started) * 1000,
            retrieval_query=query,
            result_count=len(results),
        )
        return results

    async def _keyword_search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, object],
        trace: RetrievalTrace,
    ) -> list[RetrievedChunk]:
        if self.keyword_store is None:
            return []
        started = perf_counter()
        results = await self.keyword_store.search(query, top_k=top_k, filters=filters)
        trace.add_step(
            "keyword_search",
            (perf_counter() - started) * 1000,
            retrieval_query=query,
            result_count=len(results),
            keyword_backends=self._keyword_backends(results),
            fallback_used=self._fallback_used(results),
        )
        return results

    async def _hybrid_search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, object],
        trace: RetrievalTrace,
    ) -> list[RetrievedChunk]:
        if self.keyword_store is None:
            return []
        candidate_k = top_k * self.hybrid_candidate_multiplier
        started = perf_counter()
        vector_results, keyword_results = await asyncio.gather(
            self._vector_search_without_trace(query, candidate_k, filters),
            self.keyword_store.search(query, top_k=candidate_k, filters=filters),
        )
        trace.add_step(
            "hybrid_recall",
            (perf_counter() - started) * 1000,
            retrieval_query=query,
            vector_count=len(vector_results),
            keyword_count=len(keyword_results),
            candidate_k=candidate_k,
            keyword_backends=self._keyword_backends(keyword_results),
            fallback_used=self._fallback_used(keyword_results),
        )

        fusion_started = perf_counter()
        fused = self.fusion.fuse(
            {"vector": vector_results, "keyword": keyword_results},
            top_k=top_k,
        )
        trace.add_step(
            "rrf_fusion" if isinstance(self.fusion, RRFFusion) else "fusion",
            (perf_counter() - fusion_started) * 1000,
            input_count=len(vector_results) + len(keyword_results),
            output_count=len(fused),
            implementation=type(self.fusion).__name__,
            parameters=self.fusion.parameters,
            rank_constant=self.fusion.parameters.get("rank_constant"),
        )
        return fused

    async def _vector_search_without_trace(
        self, query: str, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]:
        embedding = await self.embedder.embed_query(query)
        return await self.vector_store.search(embedding, top_k=top_k, filters=filters)

    async def _fallback_to_vector(
        self,
        query: str,
        top_k: int,
        filters: dict[str, object],
        trace: RetrievalTrace,
        requested_strategy: RetrievalStrategy,
    ) -> list[RetrievedChunk]:
        trace.add_step(
            "strategy_fallback",
            0,
            requested_strategy=requested_strategy.value,
            fallback_strategy=RetrievalStrategy.VECTOR.value,
            reason="Keyword store is not configured.",
        )
        return await self._vector_search(query, top_k, filters, trace)

    @staticmethod
    def _rerank_positions(results: Iterable[RetrievedChunk]) -> list[RetrievedChunk]:
        ranked = sorted(results, key=lambda item: (-item.score, item.chunk.id))
        return [result.model_copy(update={"rank": rank}) for rank, result in enumerate(ranked, 1)]

    @staticmethod
    def _keyword_backends(results: Iterable[RetrievedChunk]) -> list[str]:
        return sorted({result.source for result in results if result.source.startswith("keyword")})

    @staticmethod
    def _fallback_used(results: Iterable[RetrievedChunk]) -> bool:
        return any("fallback" in result.source for result in results)
