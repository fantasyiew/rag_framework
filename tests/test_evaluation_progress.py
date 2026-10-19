import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from test_evaluation import StaticRetriever
from test_rag_evaluation import EvaluationGenerator, EvaluationRetriever

from rag_framework.api import main
from rag_framework.core.models import Query
from rag_framework.evaluation import EvaluationCase, EvaluationDatasetStore, EvaluationStore, RetrievalEvaluator, RetrievalEvaluationRequest, RAGEvaluator, RAGEvaluationRequest
from rag_framework.evaluation.progress import evaluation_events
from rag_framework.pipeline.generation import GenerationPipeline


@pytest.mark.parametrize('kind', ['retrieval', 'rag'])
async def test_real_evaluator_counts_success_and_failure(kind):
    store = EvaluationStore()
    evaluator = (RetrievalEvaluator(StaticRetriever(), store) if kind == 'retrieval' else
        RAGEvaluator(GenerationPipeline(EvaluationRetriever(), EvaluationGenerator()), store))
    model = RetrievalEvaluationRequest if kind == 'retrieval' else RAGEvaluationRequest
    cases = [EvaluationCase(id=str(i), query=Query(text=text), relevant_chunk_ids=['relevant'])
             for i, text in enumerate(['question', 'fail', 'question'])]
    events = []
    report = await evaluator.evaluate(model(cases=cases), on_progress=events.append)
    assert [event['completed'] for event in events] == [1, 2, 3]
    assert events[-1]['successful'] == 2 and events[-1]['failed'] == 1
    assert all(event['total'] == 3 for event in events)
    assert report.status == 'partial' and store.get(report.id)
    assert [case.case_id for case in report.cases] == ['0', '1', '2']


async def test_stream_failure_is_safe_and_disconnect_cancels():
    class Failing:
        async def evaluate(self, request, *, on_progress):
            raise RuntimeError('private-provider-body')
    request = SimpleNamespace(cases=[None])
    frames = [frame async for frame in evaluation_events(Failing(), request)]
    assert frames[0].startswith('event: start')
    assert frames[-1].startswith('event: error')
    assert 'private-provider-body' not in ''.join(frames)
    cancelled = asyncio.Event()
    class Waiting:
        async def evaluate(self, request, *, on_progress):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    stream = evaluation_events(Waiting(), request)
    await anext(stream)
    await asyncio.sleep(0)
    await stream.aclose()
    assert cancelled.is_set()


@pytest.mark.parametrize('kind', ['retrieval', 'rag'])
async def test_stream_route_and_preflight(monkeypatch, tmp_path, kind):
    dataset_store = EvaluationDatasetStore(tmp_path / 'datasets')
    dataset = dataset_store.import_jsonl('{"query":"question","relevant_chunk_ids":["relevant"]}', name='progress')
    monkeypatch.setattr(main, 'evaluation_dataset_store', dataset_store)
    monkeypatch.setattr(main, 'knowledge_bases', SimpleNamespace(runtime=lambda key: object()))
    store = EvaluationStore()
    evaluator = (RetrievalEvaluator(StaticRetriever(), store) if kind == 'retrieval' else
        RAGEvaluator(GenerationPipeline(EvaluationRetriever(), EvaluationGenerator()), store))
    monkeypatch.setattr(main, 'retrieval_evaluator' if kind == 'retrieval' else 'rag_evaluator', evaluator)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.post(f'/v1/evaluations/{kind}/datasets/{dataset.id}/stream', json={'k':5})
        assert response.status_code == 200 and 'text/event-stream' in response.headers['content-type']
        assert 'event: start' in response.text and 'event: progress' in response.text and 'event: complete' in response.text
        frames = response.text.split('\n\n')
        complete = next(frame for frame in frames if frame.startswith('event: complete'))
        report = json.loads(complete.split('data: ', 1)[1])
        assert report['case_count'] == 1 and store.get(report['id'])
        assert (await client.post(f'/v1/evaluations/{kind}/datasets/missing/stream', json={})).status_code == 404
        assert (await client.post(f'/v1/evaluations/invalid/datasets/{dataset.id}/stream', json={})).status_code == 422
