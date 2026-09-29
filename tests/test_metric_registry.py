from types import SimpleNamespace

import pytest

from rag_framework.evaluation.registry import (
    MetricRegistry,
    average_extensions,
    retrieval_extensions,
    select_metrics,
)


def test_selection_and_builtin_comparison():
    names, answers = select_metrics('retrieval.mrr, answer.reference_similarity, retrieval.mrr')
    assert names == ['retrieval.mrr']
    assert answers == ['answer.reference_similarity']
    values = retrieval_extensions(names, ['wrong', 'right'], ['right'], {'right'}, 2)
    assert values == {'retrieval.mrr.before': 0.5, 'retrieval.mrr.after': 1.0,
                      'retrieval.mrr.delta': 0.5}
    with pytest.raises(ValueError, match='Unknown'):
        select_metrics('typo')


def test_custom_registration_and_validation():
    registry = MetricRegistry()
    registry.register('custom', lambda context: context)
    assert registry.evaluate(['custom'], 0.25) == {'custom': 0.25}
    assert registry.evaluate(['custom'], None) == {'custom': None}
    with pytest.raises(ValueError):
        registry.register('custom', lambda context: 0)
    for invalid in (True, float('nan'), float('inf'), -1, 2, 'bad'):
        with pytest.raises(ValueError):
            registry.evaluate(['custom'], invalid)


def test_aggregation_missing_is_not_zero():
    results = [SimpleNamespace(metric_extensions={'x': 0.5, 'y': None}),
               SimpleNamespace(metric_extensions={'x': None, 'y': None}),
               SimpleNamespace(metric_extensions={})]
    assert average_extensions(results) == {'x': 0.5, 'y': None}
