from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from rag_framework.api import main
from rag_framework.evaluation import EvaluationDatasetStore, EvaluationStore
from rag_framework.evaluation.models import RAGEvaluationReport, RetrievalEvaluationReport


async def test_rename_preserves_id_cases_and_history(monkeypatch, tmp_path):
    datasets = EvaluationDatasetStore(tmp_path / 'datasets')
    original = datasets.import_jsonl('{"id":"case","query":"q","relevant_chunk_ids":["chunk"],"metadata":{"type":"single_chunk"}}', name='old', description='keep-description')
    before_export = datasets.export_jsonl(original.id)
    reports = EvaluationStore(directory=tmp_path / 'reports')
    report = RetrievalEvaluationReport(status='complete', k=5, case_count=0,
        successful_case_count=0, cases=[], duration_ms=0, dataset_id=original.id)
    reports.save(report)
    monkeypatch.setattr(main, 'evaluation_dataset_store', datasets)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.patch(f'/v1/evaluation-datasets/{original.id}', json={'name':'  新名称  '})
        assert response.status_code == 200
        renamed = response.json()
        assert renamed['id'] == original.id and renamed['name'] == '新名称'
        assert renamed['created_at'] == original.created_at
        assert renamed['updated_at'] >= original.updated_at
        assert renamed['description'] == original.description
        assert (await client.get('/v1/evaluation-datasets')).json()[0]['name'] == '新名称'
        assert (await client.get(f'/v1/evaluation-datasets/{original.id}')).json()['name'] == '新名称'
        assert (await client.patch('/v1/evaluation-datasets/missing', json={'name':'new'})).status_code == 404
    assert datasets.export_jsonl(original.id) == before_export
    assert EvaluationDatasetStore(tmp_path / 'datasets').get(original.id).name == '新名称'
    assert EvaluationStore(directory=tmp_path / 'reports').get(report.id).dataset_id == original.id


@pytest.mark.parametrize('payload', [{'name':''}, {'name':'   '}, {'name':'x'*201}, {'name':None}, {'name':'valid','id':'override'}])
async def test_invalid_rename_does_not_modify_record(monkeypatch, tmp_path, payload):
    datasets = EvaluationDatasetStore(tmp_path)
    dataset = datasets.import_jsonl('{"query":"q","relevant_chunk_ids":["c"]}', name='original')
    monkeypatch.setattr(main, 'evaluation_dataset_store', datasets)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        assert (await client.patch(f'/v1/evaluation-datasets/{dataset.id}', json=payload)).status_code == 422
    assert datasets.get(dataset.id).name == 'original'


async def test_rename_write_failure_preserves_file(monkeypatch, tmp_path):
    datasets = EvaluationDatasetStore(tmp_path)
    dataset = datasets.import_jsonl('{"query":"q","relevant_chunk_ids":["c"]}', name='original')
    monkeypatch.setattr(main, 'evaluation_dataset_store', datasets)
    def fail(*args):
        raise PermissionError('private-storage-path')
    monkeypatch.setattr(datasets, 'save', fail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.patch(f'/v1/evaluation-datasets/{dataset.id}', json={'name':'new'})
    assert response.status_code == 500 and 'private-storage-path' not in response.text
    assert datasets.get(dataset.id).name == 'original'


@pytest.mark.parametrize('model', [RetrievalEvaluationReport, RAGEvaluationReport])
async def test_report_delete_persists_and_retains_snapshot(monkeypatch, tmp_path, model):
    store = EvaluationStore(directory=tmp_path / 'reports')
    snapshot = {'snapshot_id':str(uuid4()), 'settings':{'default_top_k':5}}
    store.save_snapshot(snapshot)
    report = model(status='complete', k=5, case_count=0, successful_case_count=0,
        cases=[], duration_ms=0, config_snapshot=snapshot)
    store.save(report)
    kept = report.model_copy(update={'id':'report-keep'})
    store.save(kept)
    unrelated = tmp_path / 'trace.json'
    unrelated.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(main, 'evaluation_store', store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.delete(f'/v1/evaluations/{report.id}')
        assert response.status_code == 200 and response.json()['deleted']
        assert response.json()['snapshots_retained']
        assert (await client.get(f'/v1/evaluations/{report.id}')).status_code == 404
        assert (await client.delete(f'/v1/evaluations/{report.id}')).status_code == 404
        assert [item['id'] for item in (await client.get('/v1/evaluations')).json()] == [kept.id]
    assert not store._path(report.id).exists()
    assert EvaluationStore(directory=tmp_path / 'reports').get(report.id) is None
    assert EvaluationStore(directory=tmp_path / 'reports').get(kept.id)
    assert (tmp_path / 'reports' / 'snapshots' / f"{snapshot['snapshot_id']}.json").exists()
    assert unrelated.exists()


async def test_report_delete_permission_error_keeps_memory(monkeypatch, tmp_path):
    store = EvaluationStore(directory=tmp_path)
    report = RetrievalEvaluationReport(status='complete', k=5, case_count=0,
        successful_case_count=0, cases=[], duration_ms=0)
    store.save(report)
    path = store._path(report.id)
    unlink = Path.unlink
    def fail(target, *args, **kwargs):
        if target == path:
            raise PermissionError('private-storage-path')
        return unlink(target, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail)
    monkeypatch.setattr(main, 'evaluation_store', store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.delete(f'/v1/evaluations/{report.id}')
    assert response.status_code == 500 and 'private-storage-path' not in response.text
    assert store.get(report.id) and path.exists()
    assert not store.delete('../outside')
