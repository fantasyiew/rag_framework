"""Typed metric extension registries; legacy report fields remain stable."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from rag_framework.core.models import RAGResponse

from .metrics import compute_retrieval_metrics
from .models import AnswerQualityMetrics, EvaluationCase, RetrievalMetrics


@dataclass(frozen=True)
class RetrievalMetricInput:
    retrieved_ids: list[str]
    relevant_ids: set[str]
    k: int


@dataclass(frozen=True)
class AnswerMetricInput:
    case: EvaluationCase
    response: RAGResponse
    judged_metrics: AnswerQualityMetrics


T = TypeVar('T')


class MetricRegistry(Generic[T]):
    def __init__(self):
        self.metrics: dict[str, Callable[[T], float | None]] = {}

    def register(self, name: str, metric: Callable[[T], float | None]):
        if not name or name in self.metrics or not callable(metric):
            raise ValueError('Metric name must be unique and implementation callable')
        self.metrics[name] = metric

    def evaluate(self, names: list[str], context: T) -> dict[str, float | None]:
        output = {}
        for name in names:
            value = self.metrics[name](context)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError('Metric must return a finite score in [0, 1] or None')
            output[name] = value
        return output


retrieval_metrics = MetricRegistry[RetrievalMetricInput]()
answer_metrics = MetricRegistry[AnswerMetricInput]()
for field in RetrievalMetrics.model_fields:
    retrieval_metrics.register('retrieval.' + field, lambda context, field=field: getattr(
        compute_retrieval_metrics(context.retrieved_ids, context.relevant_ids, k=context.k), field))
for field in ('groundedness', 'answer_relevancy', 'citation_validity', 'citation_correctness',
              'citation_precision', 'citation_recall', 'reference_similarity'):
    answer_metrics.register('answer.' + field, lambda context, field=field: getattr(context.judged_metrics, field))


def select_metrics(selection: str):
    names = list(dict.fromkeys(name.strip() for name in selection.split(',') if name.strip()))
    if any(name not in retrieval_metrics.metrics and name not in answer_metrics.metrics for name in names):
        raise ValueError('Unknown evaluation metric name')
    return ([name for name in names if name in retrieval_metrics.metrics],
            [name for name in names if name in answer_metrics.metrics])


def retrieval_extensions(names, before_ids, after_ids, relevant, k):
    before = retrieval_metrics.evaluate(names, RetrievalMetricInput(before_ids, relevant, k))
    after = retrieval_metrics.evaluate(names, RetrievalMetricInput(after_ids, relevant, k))
    return {**{name + '.before': value for name, value in before.items()},
            **{name + '.after': value for name, value in after.items()},
            **{name + '.delta': after[name] - value if value is not None and after[name] is not None else None
               for name, value in before.items()}}


def average_extensions(results):
    keys = dict.fromkeys(key for result in results for key in result.metric_extensions)
    return {key: (sum(values) / len(values) if values else None)
            for key in keys
            for values in [[result.metric_extensions[key] for result in results
                            if result.metric_extensions.get(key) is not None]]}
