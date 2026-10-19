import json
from uuid import uuid4

import httpx
import pytest

from rag_framework.api import main
from rag_framework.evaluation import EvaluationStore
from rag_framework.evaluation.models import RAGEvaluationReport, RetrievalEvaluationReport


def make_report(model=RetrievalEvaluationReport, **updates):
    return model(status='complete', k=5, case_count=0, successful_case_count=0,
                 cases=[], duration_ms=12.5, dataset_id='dataset', **updates)


@pytest.mark.parametrize('model', [RetrievalEvaluationReport, RAGEvaluationReport])
async def test_rename_report_preserves_results_snapshot_and_order(tmp_path, monkeypatch, model):
    store = EvaluationStore(directory=tmp_path)
    snapshot = {'snapshot_id':str(uuid4()), 'settings':{'query_planner_mode':'disabled'}}
    store.save_snapshot(snapshot)
    report = make_report(model, config_snapshot=snapshot)
    store.save(report)
    store.save(make_report(model))
    order = [item.id for item in store.list()]
    before = report.model_dump(exclude={'name'})
    snapshot_path = tmp_path / 'snapshots' / f"{snapshot['snapshot_id']}.json"
    snapshot_bytes = snapshot_path.read_bytes()
    monkeypatch.setattr(main, 'evaluation_store', store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.patch(f'/v1/evaluations/{report.id}', json={'name':'  混合检索基线  '})
        assert response.status_code == 200
        assert response.json()['name'] == '混合检索基线'
        assert (await client.get(f'/v1/evaluations/{report.id}')).json()['name'] == '混合检索基线'
        assert any(item['name'] == '混合检索基线' for item in (await client.get('/v1/evaluations')).json())
        assert (await client.patch('/v1/evaluations/missing', json={'name':'test'})).status_code == 404
    assert store.get(report.id).model_dump(exclude={'name'}) == before
    assert [item.id for item in store.list()] == order
    assert EvaluationStore(directory=tmp_path).get(report.id).name == '混合检索基线'
    assert snapshot_path.read_bytes() == snapshot_bytes


@pytest.mark.parametrize('payload', [{'name':''}, {'name':'  '}, {'name':'x'*201}, {'name':None}, {'name':'valid','k':99}])
async def test_invalid_report_name_retains_original(tmp_path, monkeypatch, payload):
    store = EvaluationStore(directory=tmp_path)
    report = make_report(name='original')
    store.save(report)
    monkeypatch.setattr(main, 'evaluation_store', store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.patch(f'/v1/evaluations/{report.id}', json=payload)
    assert response.status_code == 422
    assert store.get(report.id).name == 'original'
    assert EvaluationStore(directory=tmp_path).get(report.id).name == 'original'


async def test_report_rename_write_failure_does_not_change_memory(tmp_path, monkeypatch):
    store = EvaluationStore(directory=tmp_path)
    report = make_report(name='original')
    store.save(report)
    monkeypatch.setattr(main, 'evaluation_store', store)
    def fail(*args):
        raise PermissionError('private-storage-path')
    monkeypatch.setattr(store, '_write', fail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.patch(f'/v1/evaluations/{report.id}', json={'name':'new'})
    assert response.status_code == 500 and 'private-storage-path' not in response.text
    assert store.get(report.id) is report
    assert EvaluationStore(directory=tmp_path).get(report.id).name == 'original'


@pytest.mark.parametrize('model', [RetrievalEvaluationReport, RAGEvaluationReport])
def test_legacy_report_without_name_can_be_renamed(tmp_path, model):
    report = make_report(model)
    raw = report.model_dump(mode='json', exclude={'name'})
    (tmp_path / f'{report.id}.json').write_text(json.dumps(raw), encoding='utf-8')
    store = EvaluationStore(directory=tmp_path)
    assert store.get(report.id).name is None
    assert store.list()[0].name is None
    store.rename(report.id, 'legacy')
    assert EvaluationStore(directory=tmp_path).get(report.id).name == 'legacy'


def test_memory_only_report_rename():
    store = EvaluationStore()
    report = make_report()
    store.save(report)
    assert store.rename(report.id, 'new').name == 'new'
    with pytest.raises(KeyError):
        store.rename('../missing', 'ignored')
