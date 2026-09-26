import json

import pytest

from rag_framework.evaluation import DatasetFormatError, EvaluationDatasetStore


def test_jsonl_dataset_round_trip_and_string_query_shorthand(tmp_path) -> None:
    store = EvaluationDatasetStore(tmp_path, max_cases=10)
    content = "\n".join(
        [
            json.dumps(
                {
                    "id": "case-1",
                    "query": "东京塔有多高？",
                    "relevant_chunk_ids": ["tokyo-tower-1"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "id": "case-2",
                    "query": {"text": "浅草寺在哪里？", "filters": {"city": "东京"}},
                    "relevant_chunk_ids": ["sensoji-1", "sensoji-2"],
                    "metadata": {"category": "location"},
                },
                ensure_ascii=False,
            ),
        ]
    )

    dataset = store.import_jsonl(content, name="Tokyo QA", description="smoke set")
    reloaded_store = EvaluationDatasetStore(tmp_path)
    reloaded = reloaded_store.get(dataset.id)
    exported = reloaded_store.export_jsonl(dataset.id)

    assert reloaded is not None
    assert reloaded.name == "Tokyo QA"
    assert reloaded.cases[0].query.text == "东京塔有多高？"
    assert reloaded.cases[1].query.filters == {"city": "东京"}
    assert reloaded_store.list()[0].case_count == 2
    assert exported is not None
    exported_cases = [json.loads(line) for line in exported.splitlines()]
    assert [case["id"] for case in exported_cases] == ["case-1", "case-2"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not-json", "Line 1: invalid JSON"),
        ("[]", "Line 1: expected a JSON object"),
        ('{"query": "missing labels"}', "Line 1:"),
        ("\n", "Dataset contains no evaluation cases"),
    ],
)
def test_jsonl_dataset_reports_actionable_validation_errors(
    tmp_path, content: str, message: str
) -> None:
    store = EvaluationDatasetStore(tmp_path)

    with pytest.raises(DatasetFormatError, match=message):
        store.import_jsonl(content, name="invalid")


def test_dataset_rejects_duplicate_case_ids(tmp_path) -> None:
    store = EvaluationDatasetStore(tmp_path)
    line = json.dumps(
        {"id": "same", "query": "question", "relevant_chunk_ids": ["chunk"]}
    )

    with pytest.raises(DatasetFormatError, match="unique"):
        store.import_jsonl(f"{line}\n{line}", name="duplicates")


def test_dataset_case_limit_is_enforced(tmp_path) -> None:
    store = EvaluationDatasetStore(tmp_path, max_cases=1)
    line = json.dumps({"query": "question", "relevant_chunk_ids": ["chunk"]})

    with pytest.raises(DatasetFormatError, match="maximum of 1"):
        store.import_jsonl(f"{line}\n{line}", name="too-large")


def test_invalid_dataset_id_is_treated_as_missing(tmp_path) -> None:
    store = EvaluationDatasetStore(tmp_path)

    assert store.get("bad:id") is None
    assert store.export_jsonl("../outside") is None
