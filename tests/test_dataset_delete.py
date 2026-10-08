import httpx
import pytest

from rag_framework.api import main
from rag_framework.evaluation import EvaluationDatasetStore


@pytest.mark.asyncio
async def test_delete_imported_record_only(monkeypatch, tmp_path):
    store = EvaluationDatasetStore(tmp_path / 'records')
    monkeypatch.setattr(main, 'evaluation_dataset_store', store)
    deleted = store.import_jsonl('{"query":"a","relevant_chunk_ids":["a"]}', name='delete-me')
    kept = store.import_jsonl('{"query":"b","relevant_chunk_ids":["b"]}', name='keep-me')
    sample = tmp_path / 'sample.jsonl'
    sample.write_text('{"query":"a"}', encoding='utf-8')
    report = tmp_path / 'report.json'
    report.write_text('{}', encoding='utf-8')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.delete(f'/v1/evaluation-datasets/{deleted.id}')
        assert response.status_code == 200 and response.json()['deleted']
        assert (await client.get(f'/v1/evaluation-datasets/{deleted.id}')).status_code == 404
        assert (await client.get(f'/v1/evaluation-datasets/{deleted.id}/export')).status_code == 404
        assert (await client.delete(f'/v1/evaluation-datasets/{deleted.id}')).status_code == 404
        assert [item['id'] for item in (await client.get('/v1/evaluation-datasets')).json()] == [kept.id]
    assert sample.exists() and report.exists() and store.get(kept.id)


def test_delete_rejects_path_traversal(tmp_path):
    store = EvaluationDatasetStore(tmp_path / 'records')
    outside = tmp_path / 'outside.json'
    outside.write_text('{}', encoding='utf-8')
    assert not store.delete('../outside')
    assert not store.delete('unknown')
    assert outside.exists()


@pytest.mark.asyncio
async def test_delete_permission_failure_is_safe(monkeypatch):
    class FailingStore:
        def delete(self, identifier):
            raise PermissionError('private-path-value')
    monkeypatch.setattr(main, 'evaluation_dataset_store', FailingStore())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.delete('/v1/evaluation-datasets/record')
    assert response.status_code == 500
    assert 'private-path-value' not in response.text
