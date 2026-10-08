from pydantic import SecretStr
from rag_framework.config import Settings
from rag_framework.hot_config import isolated_settings
from rag_framework.config_workbench import validate_draft
from rag_framework.credentials import resolve_credential, credential_readiness

def base_config(**updates):
    return isolated_settings(Settings, {'embedding_mode': 'hash', 'query_planner_mode': 'disabled',
        'answer_generator_mode': 'extractive', 'evaluation_judge_mode': 'heuristic',
        'reranker_mode': 'disabled', **updates})

def test_missing_remote_key_fails_preflight(monkeypatch):
    monkeypatch.delenv('RAG_EMBEDDING_API_KEY', raising=False)
    base = base_config()
    result = validate_draft({'schema_version': 1, 'settings': {'embedding_mode': 'compatible',
        'embedding_model': 'test', 'embedding_base_url': 'https://example.com/v1'}, 'secret_refs': {}}, base)
    assert not result['valid']
    assert any(item['field'] == 'embedding_api_key' for item in result['errors'])

def test_inheritance_and_no_secret_leak(monkeypatch):
    monkeypatch.setenv('RAG_PLANNER_API_KEY', 'synthetic-private-key')
    base = base_config(answer_generator_mode='llm', evaluation_judge_mode='llm', reranker_mode='cloud')
    result = credential_readiness(base, base, {})
    assert not result['errors']
    assert result['credentials']['generation_api_key']['inherited_from'] == 'planner_api_key'
    assert 'synthetic-private-key' not in str(result)

def test_custom_reference_does_not_use_unrelated_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    base = base_config(embedding_api_key=SecretStr('other-private-key'))
    assert resolve_credential(base, 'embedding_api_key', 'MISSING_CUSTOM_KEY') is None
    monkeypatch.setenv('CUSTOM_EMBEDDING_KEY', 'custom-private-key')
    assert resolve_credential(base, 'embedding_api_key', 'CUSTOM_EMBEDDING_KEY') == 'custom-private-key'

def test_auto_warns_and_es_partial_credentials(monkeypatch):
    monkeypatch.delenv('RAG_PLANNER_API_KEY', raising=False)
    base = base_config(query_planner_mode='auto', keyword_backend='elasticsearch', elasticsearch_username='user')
    result = credential_readiness(base, base, {})
    assert result['warnings']
    assert any(item['field'] == 'elasticsearch_password' for item in result['errors'])
