from rag_framework.config_workbench import configuration_schema, validate_draft
from rag_framework.presets import SECRET_FIELDS


def test_schema_excludes_credentials_and_marks_index_changes():
    fields = configuration_schema()['fields']
    assert not set(fields) & SECRET_FIELDS
    assert 'service_preset' not in fields
    assert fields['chunk_size']['requires_rebuild_review']
    assert fields['default_top_k']['group'] == '检索与规划'


def test_draft_validation_is_isolated_and_field_errors(monkeypatch):
    monkeypatch.setenv('RAG_CHUNK_SIZE', 'invalid')
    monkeypatch.setenv('RAG_SERVICE_PRESET', 'nonexistent.json')
    assert validate_draft({'settings': {'chunk_size': 500, 'chunk_overlap': 20}})['valid']
    result = validate_draft({'settings': {'default_top_k': 0}})
    assert not result['valid']
    assert result['errors'][0]['field'] == 'default_top_k'
    assert not validate_draft({'settings': {'chunk_size': 10, 'chunk_overlap': 20}})['valid']
    assert not validate_draft({'settings': {'fusion_mode': 'unknown'}})['valid']
    assert not validate_draft({'settings': {'planner_api_key': 'do-not-echo'}})['valid']
