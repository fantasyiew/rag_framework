import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from rag_framework.api import main
from rag_framework.core.models import Query, QueryType, RetrievalStrategy
from rag_framework.evaluation import DatasetEvaluationRequest, EvaluationDatasetStore
from rag_framework.providers.router import HeuristicQueryPlanner


@pytest.mark.asyncio
async def test_plan_endpoint_returns_structured_analysis_and_decision(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "planner_runtime",
        SimpleNamespace(planner=HeuristicQueryPlanner()),
    )
    plan = await main.plan_query(Query(text="查找错误码 API-404"))

    assert plan.analysis.query_type == QueryType.EXACT_MATCH
    assert plan.decision.strategy == RetrievalStrategy.KEYWORD


@pytest.mark.asyncio
async def test_health_exposes_active_planner_without_secrets() -> None:
    payload = await main.health()

    assert payload["configured_query_planner_mode"] in {"heuristic", "llm", "auto"}
    assert payload["active_query_planner_mode"] in {"heuristic", "llm"}
    assert payload["configured_evaluation_judge_mode"] in {"heuristic", "llm", "auto"}
    assert payload["active_evaluation_judge_mode"] in {"heuristic", "llm"}
    assert "api_key" not in payload


@pytest.mark.asyncio
async def test_get_evaluation_returns_404_for_unknown_report() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await main.get_evaluation("unknown")

    assert exc_info.value.status_code == 404


def _request_with_body(body: bytes) -> Request:
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": []}, receive)


@pytest.mark.asyncio
async def test_dataset_import_list_and_export_api(monkeypatch, tmp_path) -> None:
    store = EvaluationDatasetStore(tmp_path)
    monkeypatch.setattr(main, "evaluation_dataset_store", store)
    body = json.dumps(
        {"id": "case-1", "query": "东京塔", "relevant_chunk_ids": ["chunk-1"]},
        ensure_ascii=False,
    ).encode()

    dataset = await main.import_evaluation_dataset(
        _request_with_body(body),
        name="Tokyo",
        description="API test",
    )
    summaries = await main.list_evaluation_datasets()
    response = await main.export_evaluation_dataset(dataset.id)

    assert summaries[0].id == dataset.id
    assert response.media_type == "application/x-ndjson"
    assert json.loads(response.body)["query"]["text"] == "东京塔"


@pytest.mark.asyncio
async def test_evaluate_saved_dataset_passes_dataset_identity(monkeypatch, tmp_path) -> None:
    store = EvaluationDatasetStore(tmp_path)
    dataset = store.import_jsonl(
        '{"query":"东京塔","relevant_chunk_ids":["chunk-1"]}',
        name="Tokyo",
    )

    class CapturingEvaluator:
        request = None

        async def evaluate(self, request):
            self.request = request
            return SimpleNamespace()

    evaluator = CapturingEvaluator()
    monkeypatch.setattr(main, "evaluation_dataset_store", store)
    monkeypatch.setattr(main, "retrieval_evaluator", evaluator)

    await main.evaluate_retrieval_dataset(
        dataset.id,
        DatasetEvaluationRequest(k=3, include_trace=True),
    )

    assert evaluator.request.dataset_id == dataset.id
    assert evaluator.request.k == 3
    assert evaluator.request.include_trace is True


def test_openapi_exposes_retrieval_and_rag_evaluation_workflows() -> None:
    paths = main.app.openapi()["paths"]

    assert "/v1/evaluations/retrieval" in paths
    assert "/v1/evaluations/rag" in paths
    assert "/v1/evaluations/rag/datasets/{dataset_id}" in paths
    assert "/v1/evaluations/retrieval/datasets/{dataset_id}" in paths
    assert "/v1/evaluation-datasets" in paths
    assert "/v1/evaluation-datasets/import" in paths
    assert "/v1/evaluation-datasets/{dataset_id}" in paths
    assert "/v1/evaluation-datasets/{dataset_id}/export" in paths


@pytest.mark.asyncio
async def test_dataset_routes_over_http(monkeypatch, tmp_path):
    import httpx
    monkeypatch.setattr(main, 'evaluation_dataset_store', EvaluationDatasetStore(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        empty = await client.get('/v1/evaluation-datasets')
        assert empty.status_code == 200 and empty.json() == []
        imported = await client.post('/v1/evaluation-datasets/import?name=route-test',
            content='{"query":"Tokyo","relevant_chunk_ids":["chunk-1"]}',
            headers={'Content-Type': 'application/x-ndjson'})
        assert imported.status_code == 200
        dataset_id = imported.json()['id']
        listing = await client.get('/v1/evaluation-datasets')
        assert listing.status_code == 200 and listing.json()[0]['id'] == dataset_id
        assert (await client.get(f'/v1/evaluation-datasets/{dataset_id}')).status_code == 200
        assert (await client.get(f'/v1/evaluation-datasets/{dataset_id}/export')).status_code == 200


def test_frontend_dataset_list_uses_registered_route():
    from pathlib import Path
    source = (Path(__file__).parents[1] / 'src/rag_framework/web/app.js').read_text(encoding='utf-8')
    assert "api('/v1/evaluation-datasets')" in source
    assert '/v1/evaluation-test_datasets' not in source
