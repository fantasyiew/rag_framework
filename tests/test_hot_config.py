import asyncio

import pytest
from fastapi import HTTPException

from rag_framework.config import Settings
from rag_framework.core.models import Query
from rag_framework.hot_config import RequestGate, load_managed_config, read_state, write_state
from rag_framework.presets import export_preset
from rag_framework.service import build_service


def config(tmp_path):
    return Settings(_env_file=None, query_planner_mode='disabled',
        answer_generator_mode='extractive', evaluation_judge_mode='heuristic',
        managed_config_path=tmp_path / 'config.json', chroma_directory=tmp_path / 'chroma',
        source_directory=tmp_path / 'sources', knowledge_base_directory=tmp_path / 'bases',
        evaluation_report_directory=tmp_path / 'reports', evaluation_dataset_directory=tmp_path / 'test_datasets')


async def test_apply_persist_restart_new_kb_and_reject_unsafe_change(tmp_path, monkeypatch):
    from rag_framework.api import main
    settings = config(tmp_path)
    service = build_service(settings)
    for name in ('default_runtime', 'planner_runtime', 'generator_runtime', 'judge_runtime',
                 'retrieval_evaluator', 'rag_evaluator'):
        monkeypatch.setattr(main, name, getattr(main, name))
    monkeypatch.setattr(main, 'settings', settings)
    monkeypatch.setattr(main, 'service', service)
    monkeypatch.setattr(main, 'knowledge_bases', service.knowledge_bases)
    monkeypatch.setattr(main, 'config_gate', RequestGate())
    try:
        old = service.knowledge_bases.runtime('default').retriever
        preset = export_preset(settings).model_dump()
        preset['settings']['default_top_k'] = 3
        preset['settings']['fusion_mode'] = 'weighted_sum'
        result = await main.apply_configuration({'expected_version': 0, 'preset': preset})
        assert result['applied'] and result['version'] == 1
        assert service.knowledge_bases.runtime('default').retriever is not old
        assert service.knowledge_bases.runtime('default').retriever.top_k_limit == 3
        assert (await old.planner.plan(Query(text='query'))).decision.top_k == 8
        assert (await main.planner_runtime.planner.plan(Query(text='query'))).decision.top_k == 3
        assert read_state(settings.managed_config_path)['settings']['default_top_k'] == 3
        assert load_managed_config(config(tmp_path)).default_top_k == 3
        new_id = service.knowledge_bases.create('new').id
        assert service.knowledge_bases.runtime(new_id).retriever.top_k_limit == 3
        assert (await service.knowledge_bases.runtime(new_id).retriever.planner.plan(Query(text='query'))).decision.top_k == 3
        with pytest.raises(HTTPException) as conflict:
            await main.apply_configuration({'expected_version': 0, 'preset': preset})
        assert conflict.value.status_code == 409
        preset['settings']['chunk_size'] = 900
        with pytest.raises(HTTPException):
            await main.apply_configuration({'expected_version': 1, 'preset': preset})
        assert settings.chunk_size == 800
        assert read_state(settings.managed_config_path)['version'] == 1
        preset['settings']['chunk_size'] = 800
        preset['settings']['default_top_k'] = 4
        def fail_write(*args):
            raise OSError('disk unavailable')
        monkeypatch.setattr(main, 'write_state', fail_write)
        with pytest.raises(HTTPException):
            await main.apply_configuration({'expected_version': 1, 'preset': preset})
        assert settings.default_top_k == 3
        assert read_state(settings.managed_config_path)['version'] == 1
    finally:
        await service.close()


async def test_gate_waits_for_complete_request():
    gate = RequestGate()
    entered, release, applied = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def request():
        async with gate.request():
            entered.set()
            await release.wait()
    async def update():
        async with gate.update():
            applied.set()
    reader = asyncio.create_task(request())
    await entered.wait()
    writer = asyncio.create_task(update())
    await asyncio.sleep(0)
    assert not applied.is_set()
    release.set()
    await asyncio.gather(reader, writer)
    assert applied.is_set()


def test_persisted_configuration_rejects_credentials(tmp_path):
    path = tmp_path / 'runtime.json'
    write_state(path, {'schema_version': 1, 'version': 1, 'settings': {'planner_api_key': 'bad'}})
    with pytest.raises(ValueError):
        read_state(path)
