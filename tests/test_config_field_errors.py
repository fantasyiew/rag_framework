import pytest
from rag_framework.config_workbench import validate_draft

@pytest.mark.parametrize('payload,field', [
    ({'settings': {'not_a_setting': 1}}, 'not_a_setting'),
    ({'settings': {'planner_api_key': 'private-secret'}}, 'planner_api_key'),
    ({'settings': {'service_preset': 'private-secret'}}, 'service_preset'),
    ({'secret_refs': {'embedding_api_key': 'private-secret'}}, 'embedding_api_key'),
    ({'secret_refs': {'wrong_field': 'KEY'}}, 'secret_refs.wrong_field'),
    ({'settings': {'embedding_base_url': 'https://user:private-secret@example.com/v1'}}, 'embedding_base_url'),
    ({'settings': {'embedding_base_url': ['private-secret']}}, 'embedding_base_url'),
    ({'settings': {'evaluation_metrics': 'private-secret'}}, 'evaluation_metrics'),
])
def test_reports_specific_field_without_value(payload, field):
    result = validate_draft(payload)
    assert not result['valid']
    assert result['errors'][0]['field'] == field
    assert 'private-secret' not in str(result)

def test_collects_multiple_preset_failures():
    result = validate_draft({'settings': {'unknown_option': 1, 'planner_api_key': 'hidden'},
                             'secret_refs': {'embedding_api_key': 'not-a-variable'}})
    assert {item['field'] for item in result['errors']} == {'unknown_option', 'planner_api_key', 'embedding_api_key'}
