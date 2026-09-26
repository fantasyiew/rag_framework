"""Deterministic answer-quality metrics for repeatable local evaluation."""

from __future__ import annotations

import re

from rag_framework.core.models import RAGResponse

from .models import AnswerQualityMetrics, EvaluationCase

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff\u3040-\u30ffー]+")
_CITATION_PATTERN = re.compile(r"\[(\d+)]")


def compute_answer_quality(
    case: EvaluationCase,
    response: RAGResponse,
) -> AnswerQualityMetrics:
    context_count = next(
        (
            int(step.details["context_count"])
            for step in reversed(response.retrieval.steps)
            if step.name == "generate_answer" and "context_count" in step.details
        ),
        len(response.retrieval.final_context),
    )
    contexts = response.retrieval.final_context[:context_count]
    answer_text = _CITATION_PATTERN.sub(" ", response.answer.text)
    context_text = " ".join(item.chunk.content for item in contexts)
    answer_tokens = set(_tokenize(answer_text))
    context_tokens = set(_tokenize(context_text))
    query_tokens = set(_tokenize(case.query.text))

    references = [int(value) for value in _CITATION_PATTERN.findall(response.answer.text)]
    valid_references = [number for number in references if 1 <= number <= len(contexts)]
    cited_chunk_ids = {contexts[number - 1].chunk.id for number in valid_references}
    relevant = set(case.relevant_chunk_ids)

    citation_validity = len(valid_references) / len(references) if references else 0.0
    citation_precision = (
        len(cited_chunk_ids & relevant) / len(cited_chunk_ids) if cited_chunk_ids else 0.0
    )
    return AnswerQualityMetrics(
        groundedness=_coverage(answer_tokens, context_tokens),
        answer_relevancy=_f1(answer_tokens, query_tokens),
        citation_validity=citation_validity,
        citation_correctness=citation_validity * citation_precision,
        citation_precision=citation_precision,
        citation_recall=len(cited_chunk_ids & relevant) / len(relevant),
        reference_similarity=(
            _f1(answer_tokens, set(_tokenize(case.reference_answer)))
            if case.reference_answer
            else None
        ),
    )


def average_answer_quality(metrics: list[AnswerQualityMetrics]) -> AnswerQualityMetrics:
    if not metrics:
        raise ValueError("At least one answer metric is required")
    reference_values = [
        metric.reference_similarity
        for metric in metrics
        if metric.reference_similarity is not None
    ]
    methods = {metric.method for metric in metrics}
    fallback_reasons = list(
        dict.fromkeys(
            metric.fallback_reason for metric in metrics if metric.fallback_reason is not None
        )
    )
    return AnswerQualityMetrics(
        method=methods.pop() if len(methods) == 1 else "mixed",
        fallback_used=any(metric.fallback_used for metric in metrics),
        fallback_reason=", ".join(fallback_reasons) or None,
        groundedness=_average([metric.groundedness for metric in metrics]),
        answer_relevancy=_average([metric.answer_relevancy for metric in metrics]),
        citation_validity=_average([metric.citation_validity for metric in metrics]),
        citation_correctness=_average([metric.citation_correctness for metric in metrics]),
        citation_precision=_average([metric.citation_precision for metric in metrics]),
        citation_recall=_average([metric.citation_recall for metric in metrics]),
        reference_similarity=_average(reference_values) if reference_values else None,
    )


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(text.lower()):
        value = match.group(0)
        if value.isascii():
            tokens.append(value)
        else:
            tokens.extend(value)
            tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
    return tokens


def _coverage(source: set[str], evidence: set[str]) -> float:
    return len(source & evidence) / len(source) if source else 0.0


def _f1(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    if not overlap:
        return 0.0
    precision = overlap / len(left)
    recall = overlap / len(right)
    return 2 * precision * recall / (precision + recall)


def _average(values: list[float]) -> float:
    return sum(values) / len(values)
