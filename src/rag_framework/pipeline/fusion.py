"""Rank fusion algorithms shared by hybrid and multi-query retrieval."""

from __future__ import annotations

import math

from rag_framework.contracts.providers import Fusion
from rag_framework.core.models import RetrievedChunk


class RRFFusion(Fusion):
    def __init__(self, rank_constant: int = 60):
        if rank_constant < 0:
            raise ValueError("rank_constant must be non-negative")
        self.rank_constant = rank_constant

    @property
    def parameters(self) -> dict[str, object]:
        return {"rank_constant": self.rank_constant}

    def fuse(self, result_sets, *, top_k):
        return reciprocal_rank_fusion(
            result_sets, top_k=top_k, rank_constant=self.rank_constant
        )


class WeightedSumFusion(Fusion):
    """Per-list min-max normalization followed by weighted summation."""

    def __init__(self, weights: dict[str, float], normalization: str = 'min_max'):
        if normalization != 'min_max':
            raise ValueError('WeightedSum requires min_max normalization')
        if any(not math.isfinite(v) or v < 0 for v in weights.values()):
            raise ValueError('Fusion weights must be finite and nonnegative')
        self.weights = dict(weights)
        self.normalization = normalization

    @property
    def parameters(self):
        return {'weights': self.weights, 'normalization': self.normalization,
                'constant_list_score': 1.0, 'missing_score': 0.0}

    def fuse(self, result_sets, *, top_k):
        if top_k < 1:
            raise ValueError('top_k must be positive')
        chunks, scores, components = {}, {}, {}
        for source, results in result_sets.items():
            weight = self.weights.get(source, 1.0)
            if weight == 0 or not results:
                continue
            unique = {}
            for result in results:
                if not math.isfinite(result.score):
                    raise ValueError('Fusion scores must be finite')
                previous = unique.get(result.chunk.id)
                if previous is None or result.score > previous.score:
                    unique[result.chunk.id] = result
            low = min(item.score for item in unique.values())
            high = max(item.score for item in unique.values())
            for chunk_id, item in unique.items():
                normalized = (item.score - low) / (high - low) if high != low else 1.0
                contribution = weight * normalized
                chunks.setdefault(chunk_id, item.chunk)
                scores[chunk_id] = scores.get(chunk_id, 0.0) + contribution
                components.setdefault(chunk_id, {}).update({source: item.score,
                    source + ':normalized': normalized, source + ':contribution': contribution})
        ranked = sorted(scores, key=lambda key: (-scores[key], key))[:top_k]
        return [RetrievedChunk(chunk=chunks[key], score=scores[key], source='hybrid', rank=rank,
                component_scores={**components[key], 'weighted_sum': scores[key]})
                for rank, key in enumerate(ranked, 1)]


def reciprocal_rank_fusion(
    result_sets: dict[str, list[RetrievedChunk]], *, top_k: int, rank_constant: int = 60
) -> list[RetrievedChunk]:
    """Fuse rankings without assuming comparable provider score scales."""
    if rank_constant < 0:
        raise ValueError("rank_constant must be non-negative")

    fused_scores: dict[str, float] = {}
    chunks: dict[str, RetrievedChunk] = {}
    component_scores: dict[str, dict[str, float]] = {}

    for source, results in result_sets.items():
        for rank, result in enumerate(results, start=1):
            chunk_id = result.chunk.id
            chunks.setdefault(chunk_id, result)
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1 / (
                rank_constant + rank
            )
            scores = component_scores.setdefault(chunk_id, {})
            scores[source] = result.score

    ranked_ids = sorted(fused_scores, key=lambda chunk_id: (-fused_scores[chunk_id], chunk_id))
    return [
        RetrievedChunk(
            chunk=chunks[chunk_id].chunk,
            score=fused_scores[chunk_id],
            source="hybrid",
            rank=rank,
            component_scores={**component_scores[chunk_id], "rrf": fused_scores[chunk_id]},
        )
        for rank, chunk_id in enumerate(ranked_ids[:top_k], start=1)
    ]
