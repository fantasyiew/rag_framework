import pytest

from rag_framework.config import Settings
from rag_framework.core.models import Chunk, RetrievedChunk
from rag_framework.pipeline.fusion import WeightedSumFusion
from rag_framework.providers.algorithm_factory import build_fusion


def item(name, score):
    return RetrievedChunk(chunk=Chunk(id=name, content=name, document_id=name, index=0),
                          score=score, rank=1, source='test')


def test_weighted_normalization_contributions_and_no_mutation():
    vector = [item('a', -0.5), item('b', 0.5)]
    fusion = build_fusion(Settings(_env_file=None, fusion_mode='weighted_sum',
                                  fusion_weights={'vector': 0.25, 'keyword': 0.75}))
    results = fusion.fuse({'vector': vector, 'keyword': [item('a', 200), item('b', 100)]}, top_k=2)
    assert [r.chunk.id for r in results] == ['a', 'b']
    assert results[0].score == 0.75
    assert results[0].component_scores['keyword:contribution'] == 0.75
    assert vector[0].score == -0.5


def test_weighted_empty_constant_duplicate_and_zero_weight():
    fusion = WeightedSumFusion({'off': 0})
    results = fusion.fuse({'x': [item('b', 2), item('a', 2), item('a', 2)],
                           'off': [item('hidden', 9)], 'empty': []}, top_k=10)
    assert [(r.chunk.id, r.score) for r in results] == [('a', 1), ('b', 1)]
    assert fusion.fuse({}, top_k=1) == []


@pytest.mark.parametrize('weight', [-1, float('nan'), float('inf')])
def test_weighted_rejects_invalid_weight(weight):
    with pytest.raises(ValueError):
        WeightedSumFusion({'vector': weight})


def test_weighted_rejects_invalid_score_and_normalization():
    with pytest.raises(ValueError):
        WeightedSumFusion({}, 'none')
    with pytest.raises(ValueError):
        WeightedSumFusion({}).fuse({'x': [item('a', float('nan'))]}, top_k=1)
