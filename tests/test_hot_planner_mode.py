import pytest
from pydantic import SecretStr
from test_hot_config import config

from rag_framework.config_workbench import configuration_schema
from rag_framework.hot_config import RequestGate, load_managed_config, read_state
from rag_framework.presets import export_preset
from rag_framework.service import build_service


@pytest.fixture
async def runtime(tmp_path, monkeypatch):
    from rag_framework.api import main
    settings = config(tmp_path).model_copy(update={'planner_api_key': SecretStr('offline-test-key')})
    monkeypatch.delenv('RAG_PLANNER_API_KEY', raising=False)
    service = build_service(settings)
    for name in ('default_runtime', 'planner_runtime', 'generator_runtime', 'judge_runtime', 'retrieval_evaluator', 'rag_evaluator'):
        monkeypatch.setattr(main, name, getattr(main, name))
    monkeypatch.setattr(main, 'settings', settings)
    monkeypatch.setattr(main, 'service', service)
    monkeypatch.setattr(main, 'knowledge_bases', service.knowledge_bases)
    monkeypatch.setattr(main, 'config_gate', RequestGate())
    try:
        yield main, service, settings
    finally:
        await service.close()


async def test_planner_mode_applies_across_kbs_and_persists(runtime, tmp_path):
    main, service, settings = runtime
    manager = service.knowledge_bases
    other = manager.create('other').id
    original = {key: manager.runtime(key) for key in ('default', other)}
    assert configuration_schema()['fields']['query_planner_mode']['activation'] == 'hot'
    for version, mode in enumerate(['heuristic', 'llm', 'auto', 'disabled'], 1):
        preset = export_preset(settings).model_dump()
        preset['settings']['query_planner_mode'] = mode
        result = await main.apply_configuration({'expected_version': version - 1, 'preset': preset})
        assert result['applied'] and result['version'] == version
        assert settings.query_planner_mode == mode
        assert service.planner_runtime.configured_mode == mode
        assert service.planner_runtime.active_mode == ('llm' if mode in {'llm', 'auto'} else mode)
        for key, old in original.items():
            current = manager.runtime(key)
            assert current.retriever.planner is service.planner_runtime.planner
            assert current.vector_store is old.vector_store
            assert current.embedder is old.embedder and current.index_state is old.index_state
        assert read_state(settings.managed_config_path)['settings']['query_planner_mode'] == mode
        assert load_managed_config(config(tmp_path)).query_planner_mode == mode
    new = manager.create('after-change').id
    assert manager.runtime(new).retriever.planner is service.planner_runtime.planner


async def test_missing_llm_key_retains_previous_mode(runtime):
    main, service, settings = runtime
    settings.planner_api_key = None
    old = service.planner_runtime
    preset = export_preset(settings).model_dump()
    preset['settings']['query_planner_mode'] = 'llm'
    result = await main.apply_configuration({'expected_version': 0, 'preset': preset})
    assert not result['valid'] and not result['applied']
    assert any(error['field'] == 'planner_api_key' for error in result['errors'])
    assert settings.query_planner_mode == 'disabled' and service.planner_runtime is old
    assert not settings.managed_config_path.exists()


async def test_mode_change_write_failure_rolls_back(runtime, monkeypatch):
    from fastapi import HTTPException
    main, service, settings = runtime
    old = service.planner_runtime
    preset = export_preset(settings).model_dump()
    preset['settings']['query_planner_mode'] = 'heuristic'
    def fail(*args):
        raise OSError('private-storage-error')
    monkeypatch.setattr(main, 'write_state', fail)
    with pytest.raises(HTTPException) as error:
        await main.apply_configuration({'expected_version': 0, 'preset': preset})
    assert error.value.status_code == 422
    assert service.planner_runtime is old and settings.query_planner_mode == 'disabled'
    assert not settings.managed_config_path.exists()
