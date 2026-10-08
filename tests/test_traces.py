import asyncio
from types import SimpleNamespace

import httpx
from test_retrieval import StubEmbedder, StubVectorStore, make_result

from rag_framework.api import main
from rag_framework.core.models import Query
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers.fixed_planner import FixedQueryPlanner
from rag_framework.providers.generation import ExtractiveAnswerGenerator
from rag_framework.traces import TraceStore, capture, complete, current_trace


def runtime(generator=None):
    retriever = AdaptiveRetriever(StubVectorStore([make_result('chunk')]), StubEmbedder(),
                                  FixedQueryPlanner('vector', 8, False))
    return SimpleNamespace(retriever=retriever, generation_pipeline=GenerationPipeline(
        retriever, generator or ExtractiveAnswerGenerator()),
        indexing_pipeline=SimpleNamespace(check_index=noop))


async def noop():
    pass


class FailingGenerator(ExtractiveAnswerGenerator):
    async def generate(self, query, contexts):
        raise RuntimeError('private provider error')

    async def stream(self, query, contexts):
        yield 'partial'
        raise RuntimeError('private provider error')


async def test_chat_trace_snapshot_lookup_and_step(monkeypatch, tmp_path):
    store = TraceStore(tmp_path / 'traces.sqlite3')
    monkeypatch.setattr(main, 'trace_store', lambda: store)
    monkeypatch.setattr(main, 'knowledge_bases', SimpleNamespace(runtime=lambda key: runtime(), get=lambda key: SimpleNamespace(status='active')))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.post('/v1/chat', json={'text':'query', 'conversation_id':'one'})
        assert response.status_code == 200
        trace = response.json()['retrieval']
        assert trace['status'] == 'completed'
        record = (await client.get('/v1/traces/' + trace['id'])).json()
        assert record['answer']['text']
        assert record['trace']['final_context'][0]['chunk']['content']
        ids = [step['id'] for step in trace['steps']]
        assert len(set(ids)) == len(ids)
        step = await client.get('/v1/traces/' + trace['id'] + '/steps/' + ids[-1])
        assert step.json()['step']['name'] == 'generate_answer'
        assert (await client.get('/v1/traces/' + trace['id'] + '/steps/missing')).status_code == 404
        assert (await client.get('/v1/traces/missing')).status_code == 404
        assert len((await client.get('/v1/traces?conversation_id=one')).json()) == 1
        assert (await client.get('/v1/traces?conversation_id=other')).json() == []
        retrieved = await client.post('/v1/retrieve', json={'text':'query'})
        assert retrieved.json()['status'] == 'completed'
        streamed = await client.post('/v1/chat/stream', json={'text':'query'})
        assert 'event: complete' in streamed.text
        assert '"status": "completed"' in streamed.text
        monkeypatch.setattr(main.knowledge_bases, 'get', lambda key: SimpleNamespace(status='deleted'))
        deleted_record = (await client.get('/v1/traces/' + trace['id'])).json()
        assert deleted_record['trace']['knowledge_base_status'] == 'deleted'
        assert deleted_record['trace']['final_context'] == record['trace']['final_context']
    reopened = TraceStore(tmp_path / 'traces.sqlite3')
    assert record['trace'].pop('knowledge_base_status') == 'active'
    assert reopened.get(trace['id']) == record


async def test_failed_generation_preserves_retrieval(monkeypatch, tmp_path):
    store = TraceStore(tmp_path / 'traces.sqlite3')
    monkeypatch.setattr(main, 'trace_store', lambda: store)
    monkeypatch.setattr(main, 'knowledge_bases',
                        SimpleNamespace(runtime=lambda key: runtime(FailingGenerator())))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.post('/v1/chat', json={'text':'query'})
        assert response.status_code == 500
        trace_id = response.json()['detail']['trace_id']
        trace = store.get(trace_id)['trace']
        assert trace['status'] == 'failed'
        assert trace['final_context']
        assert trace['steps'][-1]['name'] == 'execution_error'
        assert 'private provider error' not in response.text
        stream = await client.post('/v1/chat/stream', json={'text':'query'})
        assert 'event: trace' in stream.text and 'event: error' in stream.text
        records = store.list()
        assert len(records) == 2
        assert all(record['trace']['status'] == 'failed' for record in records)
        assert current_trace.get() is None


async def test_task_isolation_and_bounded_retention(tmp_path):
    store = TraceStore(tmp_path / 'traces.sqlite3', limit=2)
    async def run(text):
        async with capture(store, Query(text=text)) as trace:
            await asyncio.sleep(0.01)
            assert current_trace.get().query.text == text
            trace.add_step('same', 1)
            trace.add_step('same', 1)
            await complete(store, trace)
        return trace.id
    ids = await asyncio.gather(run('one'), run('two'))
    assert ids[0] != ids[1]
    await run('three')
    assert len(store.list()) == 2
    assert current_trace.get() is None
