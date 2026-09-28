"""Rank fusion algorithms shared by hybrid and multi-query retrieval."""

from __future__ import annotations

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
