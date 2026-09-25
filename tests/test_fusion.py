from rag_framework.core.models import Chunk, RetrievedChunk
from rag_framework.pipeline.fusion import reciprocal_rank_fusion


def result(chunk_id: str, score: float, source: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(id=chunk_id, document_id=f"doc-{chunk_id}", index=0, content=chunk_id),
        score=score,
        source=source,
        rank=rank,
        component_scores={source: score},
    )


def test_rrf_rewards_chunks_found_by_multiple_retrievers() -> None:
    fused = reciprocal_rank_fusion(
        {
            "vector": [result("shared", 0.7, "vector", 1), result("vector", 0.6, "vector", 2)],
            "keyword": [result("keyword", 9.0, "keyword", 1), result("shared", 4.0, "keyword", 2)],
        },
        top_k=3,
    )

    assert fused[0].chunk.id == "shared"
    assert fused[0].source == "hybrid"
    assert set(fused[0].component_scores) == {"vector", "keyword", "rrf"}


def test_rrf_rejects_negative_rank_constant() -> None:
    try:
        reciprocal_rank_fusion({}, top_k=1, rank_constant=-1)
    except ValueError as error:
        assert "rank_constant" in str(error)
    else:
        raise AssertionError("Expected ValueError")
