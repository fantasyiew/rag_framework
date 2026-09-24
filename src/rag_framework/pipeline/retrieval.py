"""Adaptive retrieval orchestration with full decision trace."""

from __future__ import annotations

from time import perf_counter

from rag_framework.contracts.providers import Embedder, QueryRouter, Reranker, VectorStore
from rag_framework.core.models import Query, RetrievalTrace, RetrievedChunk


class AdaptiveRetriever:
    def __init__(
        self, vector_store: VectorStore, embedder: Embedder, router: QueryRouter, reranker: Reranker | None = None
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.router = router
        self.reranker = reranker

    async def retrieve(self, query: Query) -> RetrievalTrace:
        trace = RetrievalTrace(query=query)
        started = perf_counter()
        plan = await self.router.plan(query)
        trace.plan = plan
        trace.add_step("route_query", (perf_counter() - started) * 1000, plan=plan.model_dump())

        queries = [query.text, *plan.rewritten_queries] if plan.rewrite_required else [query.text]
        candidates: dict[str, RetrievedChunk] = {}
        for retrieval_query in dict.fromkeys(queries):
            search_started = perf_counter()
            embedding = await self.embedder.embed_query(retrieval_query)
            results = await self.vector_store.search(
                embedding, top_k=plan.top_k, filters={**query.filters, **plan.filters}
            )
            trace.add_step(
                "vector_search",
                (perf_counter() - search_started) * 1000,
                retrieval_query=retrieval_query,
                result_count=len(results),
            )
            for result in results:
                previous = candidates.get(result.chunk.id)
                if previous is None or result.score > previous.score:
                    candidates[result.chunk.id] = result

        trace.candidates = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
        if self.reranker and trace.plan.rerank:
            rerank_started = perf_counter()
            trace.final_context = await self.reranker.rerank(query.text, trace.candidates)
            trace.add_step("rerank", (perf_counter() - rerank_started) * 1000)
        else:
            trace.final_context = trace.candidates[: plan.top_k]
        return trace
