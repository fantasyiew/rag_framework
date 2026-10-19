import json

import pytest
from pydantic import SecretStr
from test_evaluation import StaticRetriever
from test_index_safety import config
from test_rag_evaluation import EvaluationGenerator, EvaluationRetriever

from rag_framework.core.models import Query
from rag_framework.evaluation import (
    EvaluationCase,
    EvaluationStore,
    RAGEvaluationRequest,
    RAGEvaluator,
    RetrievalEvaluationRequest,
    RetrievalEvaluator,
)
from rag_framework.evaluation.snapshots import digest
from rag_framework.knowledge_bases.bindings import embedding_profile
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.service import build_service


@pytest.mark.parametrize('kind', ['retrieval', 'rag'])
async def test_snapshot_persisted_before_case_and_frozen(tmp_path, kind, monkeypatch):
    store = EvaluationStore(directory=tmp_path / 'reports')
    base = {'settings': {'query_planner_mode': 'heuristic', 'default_top_k': 8}, 'config_version': 9}
    evaluator = (RetrievalEvaluator(StaticRetriever(), store, config_snapshot_provider=lambda: base) if kind == 'retrieval' else
        RAGEvaluator(GenerationPipeline(EvaluationRetriever(), EvaluationGenerator()), store, config_snapshot_provider=lambda: base))
    run = evaluator._evaluate_case
    captured = []
    async def check_before(case, request):
        paths = list((tmp_path / 'reports' / 'snapshots').glob('*.json'))
        assert len(paths) == 1
        snapshot = json.loads(paths[0].read_text('utf-8'))
        assert snapshot['settings']['default_top_k'] == 8
        assert snapshot['evaluation']['k'] == 3
        captured.append(snapshot)
        base['settings']['default_top_k'] = 99
        return await run(case, request)
    monkeypatch.setattr(evaluator, '_evaluate_case', check_before)
    model = RetrievalEvaluationRequest if kind == 'retrieval' else RAGEvaluationRequest
    request = model(cases=[EvaluationCase(query=Query(text='question'), relevant_chunk_ids=['relevant'])], k=3, dataset_id='dataset-v1')
    report = await evaluator.evaluate(request)
    assert report.config_snapshot == captured[0]
    snapshot = report.config_snapshot.copy()
    checksum = snapshot.pop('snapshot_hash')
    assert digest(snapshot) == checksum
    loaded = EvaluationStore(directory=tmp_path / 'reports').get(report.id)
    assert loaded.config_snapshot == report.config_snapshot
    assert loaded.config_snapshot['settings']['default_top_k'] == 8


@pytest.mark.parametrize('kind', ['retrieval', 'rag'])
async def test_snapshot_write_failure_prevents_case_execution(tmp_path, monkeypatch, kind):
    store = EvaluationStore(directory=tmp_path)
    evaluator = (RetrievalEvaluator(StaticRetriever(), store) if kind == 'retrieval' else
        RAGEvaluator(GenerationPipeline(EvaluationRetriever(), EvaluationGenerator()), store))
    def fail(snapshot):
        raise OSError('disk full')
    monkeypatch.setattr(store, 'save_snapshot', fail)
    executed = []
    async def never(*args):
        executed.append(True)
    monkeypatch.setattr(evaluator, '_evaluate_case', never)
    model = RetrievalEvaluationRequest if kind == 'retrieval' else RAGEvaluationRequest
    with pytest.raises(OSError):
        await evaluator.evaluate(model(cases=[EvaluationCase(query=Query(text='q'), relevant_chunk_ids=['relevant'])]))
    assert not executed


async def test_service_snapshot_uses_bound_embedding_and_current_config(tmp_path):
    settings = config(tmp_path, planner_api_key=SecretStr('private-snapshot-key'))
    service = build_service(settings)
    try:
        key = service.knowledge_bases.create('other', embedding_profile(config(tmp_path, embedding_dimensions=32))).id
        service.settings.planner_base_url = 'https://user:private-snapshot-key@example.com/v1?secret=yes'
        evaluator = service.retrieval_evaluator(key)
        service.settings.default_top_k = 3
        snapshot = evaluator.config_snapshot_provider()
        assert snapshot['settings']['default_top_k'] == 3
        assert snapshot['settings']['embedding_dimensions'] == 16
        assert snapshot['embedding_binding']['settings']['embedding_dimensions'] == 32
        assert snapshot['effective_index_fingerprint']['embedding']['dimensions'] == 32
        assert 'private-snapshot-key' not in json.dumps(snapshot)
        assert 'secret_refs' not in snapshot['embedding_binding']
    finally:
        await service.close()
