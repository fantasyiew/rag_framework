from unittest.mock import Mock

import pytest

from rag_framework.config import Settings
from rag_framework.core.models import Chunk, Query, RetrievedChunk
from rag_framework.providers.generation import LangChainAnswerGenerator


@pytest.mark.parametrize('template', ['{question}', '{context}', '{context} {question} {unknown}',
                                     '{context.__class__} {question}', '{context!r} {question}',
                                     '{context:10} {question}', '{context} {question} {'])
def test_invalid_templates_rejected(template):
    with pytest.raises(ValueError):
        Settings(_env_file=None, generation_user_prompt=template)


def test_custom_template_renders_evidence_without_recursive_interpolation():
    template = '证据：{context}\n问题：{question}\n历史：{history}\n格式示例：{{"answer":"..."}}'
    settings = Settings(_env_file=None, generation_user_prompt=template)
    generator = LangChainAnswerGenerator(Mock(), model_name='test',
        system_prompt='custom rules', user_prompt=settings.generation_user_prompt)
    context = RetrievedChunk(chunk=Chunk(id='c', document_id='d', index=0,
        content='Evidence with {question} literal'), score=1, rank=1, source='test')
    messages = generator._messages(Query(text='my question', history=['previous']), [context])
    assert messages[0].content == 'custom rules'
    assert '[1]' in messages[1].content
    assert 'Evidence with {question} literal' in messages[1].content
    assert '问题：my question' in messages[1].content
    assert '{"answer":"..."}' in messages[1].content
    assert generator.prompt_hash != LangChainAnswerGenerator(Mock(), model_name='test').prompt_hash
