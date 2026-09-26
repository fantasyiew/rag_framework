"""Deterministic binary-relevance retrieval metrics."""

from __future__ import annotations

import math

from .models import MetricComparison, MetricDelta, RetrievalMetrics


def compute_retrieval_metrics(
    retrieved_chunk_ids: list[str], relevant_chunk_ids: set[str], *, k: int
) -> RetrievalMetrics:
    ranked = list(dict.fromkeys(retrieved_chunk_ids))[:k]
    relevance = [1 if chunk_id in relevant_chunk_ids else 0 for chunk_id in ranked]
    hits = sum(relevance)
    reciprocal_rank = next(
        (1.0 / rank for rank, relevant in enumerate(relevance, 1) if relevant),
        0.0,
    )
    dcg = sum(relevant / math.log2(rank + 1) for rank, relevant in enumerate(relevance, 1))
    ideal_hits = min(len(relevant_chunk_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return RetrievalMetrics(
        hit_rate=1.0 if hits else 0.0,
        precision_at_k=hits / k,
        recall_at_k=hits / len(relevant_chunk_ids),
        mrr=reciprocal_rank,
        ndcg_at_k=dcg / idcg if idcg else 0.0,
    )


def compare_metrics(before: RetrievalMetrics, after: RetrievalMetrics) -> MetricComparison:
    return MetricComparison(
        before=before,
        after=after,
        delta=MetricDelta(
            hit_rate=after.hit_rate - before.hit_rate,
            precision_at_k=after.precision_at_k - before.precision_at_k,
            recall_at_k=after.recall_at_k - before.recall_at_k,
            mrr=after.mrr - before.mrr,
            ndcg_at_k=after.ndcg_at_k - before.ndcg_at_k,
        ),
    )
