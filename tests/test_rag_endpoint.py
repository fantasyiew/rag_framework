from types import SimpleNamespace

import httpx
import pytest

from rag_framework.api import main
from rag_framework.core.models import Chunk, RetrievedChunk, GeneratedAnswer, RAGResponse
from rag_framework.traces import TraceStore, current_trace


@pytest.mark.parametrize('include_trace', [False, True])
async def test_rag_response_and_durable_trace(monkeypatch, tmp_path, include_trace):
    store = TraceStore(tmp_path / 'traces.sqlite3')
    monkeypatch.setattr(main, 'trace_store', lambda: store)
    async def run(query):
        trace = current_trace.get()
        trace.final_context = [RetrievedChunk(chunk=Chunk(id=f'chunk-{i}', document_id='doc', index=i,
            content='evidence', metadata={'title': 'test'}), score=1.0, source='vector', rank=i+1) for i in range(3)]
        return RAGResponse(retrieval=trace, answer=GeneratedAnswer(text='final answer', model='test-model'))
    pipeline = SimpleNamespace(run=run, max_context_chunks=2)
    monkeypatch.setattr(main, 'knowledge_bases', SimpleNamespace(runtime=lambda key: SimpleNamespace(generation_pipeline=pipeline)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.post('/v1/rag', json={'query': 'question', 'conversation_id': 'conversation', 'include_trace': include_trace})
    assert response.status_code == 200
    payload = response.json()
    assert payload['answer'] == 'final answer'
    assert payload['generation']['status'] == 'completed'
    assert len(payload['contexts']) == 2
    assert ('trace' in payload) == include_trace
    assert store.get(payload['trace_id'])['trace']['status'] == 'completed'
    assert payload['config_version'] >= 0 and len(payload['config_hash']) == 64
    assert payload['duration_ms'] >= 0


@pytest.mark.parametrize('text,count,fallback,status', [('',1,False,'empty_answer'), ('answer',0,False,'no_context'), ('answer',1,True,'fallback')])
async def test_rag_generation_states(monkeypatch, tmp_path, text, count, fallback, status):
    monkeypatch.setattr(main, 'trace_store', lambda: TraceStore(tmp_path / 'traces.sqlite3'))
    async def run(query):
        trace = current_trace.get()
        trace.final_context = [RetrievedChunk(chunk=Chunk(document_id='doc', index=0, content='data'), score=1, source='vector', rank=1)] * count
        return RAGResponse(retrieval=trace, answer=GeneratedAnswer(text=text, model='test', fallback_used=fallback))
    monkeypatch.setattr(main, 'knowledge_bases', SimpleNamespace(runtime=lambda key: SimpleNamespace(generation_pipeline=SimpleNamespace(run=run, max_context_chunks=2))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.post('/v1/rag', json={'query': 'question'})
    assert response.json()['generation']['status'] == status


async def test_rag_rejects_overrides_and_unknown_kb(monkeypatch):
    def missing(key):
        raise KeyError(key)
    monkeypatch.setattr(main, 'knowledge_bases', SimpleNamespace(runtime=missing))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        assert (await client.post('/v1/rag', json={'query': 'question'})).status_code == 404
        assert (await client.post('/v1/rag', json={'query': ' '})).status_code == 422
        assert (await client.post('/v1/rag', json={'query': 'question', 'model': 'override'})).status_code == 422


async def test_rag_failure_has_trace_without_provider_body(monkeypatch, tmp_path):
    store = TraceStore(tmp_path / 'traces.sqlite3')
    monkeypatch.setattr(main, 'trace_store', lambda: store)
    async def run(query):
        raise RuntimeError('private-api-key provider-message')
    monkeypatch.setattr(main, 'knowledge_bases', SimpleNamespace(runtime=lambda key: SimpleNamespace(generation_pipeline=SimpleNamespace(run=run))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.post('/v1/rag', json={'query': 'question'})
    assert response.status_code == 500
    assert 'private-api-key' not in response.text
    assert store.get(response.json()['detail']['trace_id'])['trace']['status'] == 'failed'
