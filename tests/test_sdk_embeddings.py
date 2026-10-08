from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from rag_framework.config import Settings
from rag_framework.config_workbench import configuration_schema, validate_draft
from rag_framework.core.vectors import EmbeddingError
from rag_framework.hot_config import isolated_settings
from rag_framework.providers.embedding_factory import build_embedder, embedders
from rag_framework.providers.sdk_embeddings import DashScopeClient


def config(mode, **changes):
    return isolated_settings(Settings, {'embedding_mode': mode, 'embedding_model': 'test-model',
        'embedding_dimensions': 2, 'embedding_api_key': SecretStr('synthetic-key'), **changes})


def test_registry_and_optional_urls():
    assert {'openai', 'dashscope'} <= set(configuration_schema()['fields']['embedding_mode']['enum'])
    for mode in ('openai', 'dashscope'):
        base = config(mode)
        assert validate_draft({'settings': {'embedding_mode': mode, 'embedding_model': 'test-model'}}, base)['valid']


@pytest.mark.asyncio
async def test_openai_component_and_fingerprint():
    pytest.importorskip('langchain_openai')
    runtime = build_embedder(config('openai'))
    adapter = runtime.embedder
    assert adapter.component.openai_api_base == 'https://api.openai.com/v1'
    assert adapter.component.dimensions == 2
    async def fake(texts, **kwargs):
        return [[1.0, 2.0] for _ in texts]
    adapter.component.__dict__['aembed_documents'] = fake
    assert await adapter.embed_documents(['a', 'b']) == [[1.0, 2.0], [1.0, 2.0]]
    assert await adapter.embed_documents([]) == []
    assert await adapter.embed_query('a') == [1.0, 2.0]
    assert 'synthetic-key' not in str(runtime.fingerprint)
    explicit = build_embedder(config('openai', embedding_base_url='https://api.openai.com/v1/'))
    assert explicit.fingerprint == runtime.fingerprint
    await explicit.embedder.close()
    await adapter.close()
    assert adapter.async_client.is_closed and adapter.sync_client.is_closed


@pytest.mark.asyncio
async def test_dashscope_real_component_with_fake_transport(monkeypatch):
    sdk = pytest.importorskip('dashscope')
    pytest.importorskip('langchain_community')
    monkeypatch.setattr(sdk, 'api_key', 'global-key')
    old_endpoint = sdk.base_http_api_url
    calls = []
    def fake(**kwargs):
        calls.append(kwargs)
        size = len(kwargs['input']) if isinstance(kwargs['input'], list) else 1
        return SimpleNamespace(status_code=200, output={'embeddings': [
            {'text_index': i, 'embedding': [float(i), 2.0]} for i in reversed(range(size))]})
    monkeypatch.setattr(sdk.TextEmbedding, 'call', fake)
    first = build_embedder(config('dashscope', embedding_batch_size=2))
    second = build_embedder(config('dashscope', embedding_api_key=SecretStr('second-key'),
        embedding_base_url='https://example.com/api/v1', embedding_send_dimensions=False))
    assert await first.embedder.embed_documents(['a', 'b', 'c']) == [[0.0, 2.0], [1.0, 2.0], [0.0, 2.0]]
    assert await second.embedder.embed_query('query') == [0.0, 2.0]
    assert calls[0]['api_key'] == 'synthetic-key'
    assert calls[0]['base_address'] == 'https://dashscope.aliyuncs.com/api/v1'
    assert calls[0]['dimension'] == 2 and calls[0]['request_timeout'] == 30.0
    assert calls[-1]['api_key'] == 'second-key' and calls[-1]['text_type'] == 'query'
    assert 'dimension' not in calls[-1]
    assert sdk.api_key == 'global-key' and sdk.base_http_api_url == old_endpoint
    assert first.fingerprint != second.fingerprint
    assert await first.embedder.embed_documents([]) == []


@pytest.mark.asyncio
async def test_provider_failure_is_sanitized(monkeypatch):
    sdk = pytest.importorskip('dashscope')
    pytest.importorskip('langchain_community')
    def fail(**kwargs):
        raise RuntimeError('synthetic-key provider-body')
    monkeypatch.setattr(sdk.TextEmbedding, 'call', fail)
    adapter = build_embedder(config('dashscope')).embedder
    with pytest.raises(EmbeddingError) as exc:
        await adapter.embed_query('a')
    assert 'synthetic-key' not in str(exc.value)
    assert 'provider-body' not in str(exc.value)


def test_dashscope_client_checks_indices_and_dimensions():
    sdk = SimpleNamespace(call=lambda **kw: SimpleNamespace(status_code=200,
        output={'embeddings': [{'text_index': 2, 'embedding': [1.0]}]}))
    with pytest.raises(EmbeddingError):
        DashScopeClient(config('dashscope'), 'https://example.com/api/v1', sdk).call(input=['a'])


def test_extension_registration_remains_available(monkeypatch):
    from rag_framework.providers.hash_embedder import HashEmbedder
    monkeypatch.setattr(embedders, 'factories', dict(embedders.factories))
    embedders.register('test_extension', lambda settings: HashEmbedder(settings.embedding_dimensions))
    assert build_embedder(config('test_extension')).active_mode == 'test_extension'
    assert 'test_extension' in configuration_schema()['fields']['embedding_mode']['enum']


@pytest.mark.asyncio
async def test_wrong_dimensions_fail_without_fallback(monkeypatch):
    sdk = pytest.importorskip('dashscope')
    pytest.importorskip('langchain_community')
    monkeypatch.setattr(sdk.TextEmbedding, 'call', lambda **kwargs: SimpleNamespace(status_code=200,
        output={'embeddings': [{'text_index': 0, 'embedding': [1.0]}]}))
    adapter = build_embedder(config('dashscope')).embedder
    with pytest.raises(EmbeddingError):
        await adapter.embed_documents(['a'])


@pytest.mark.asyncio
async def test_dashscope_sdk_request_boundary(monkeypatch):
    pytest.importorskip('dashscope')
    pytest.importorskip('langchain_community')
    from dashscope.api_entities.dashscope_response import DashScopeAPIResponse
    from dashscope.api_entities.http_request import HttpRequest
    requests = []
    def fake(request):
        requests.append(request)
        return DashScopeAPIResponse(status_code=200, output={'embeddings': [
            {'text_index': 0, 'embedding': [1.0, 2.0]}]})
    monkeypatch.setattr(HttpRequest, 'call', fake)
    adapter = build_embedder(config('dashscope', embedding_request_timeout=7,
        embedding_base_url='https://example.com/api/v1')).embedder
    assert await adapter.embed_query('query') == [1.0, 2.0]
    assert requests[0].url == 'https://example.com/api/v1/services/embeddings/text-embedding/text-embedding'
    assert requests[0].timeout == 7
    assert requests[0].headers['Authorization'] == 'Bearer synthetic-key'


@pytest.mark.parametrize('mode', ['openai', 'dashscope'])
def test_missing_key_and_unsafe_endpoint(mode):
    with pytest.raises(ValueError, match='embedding_api_key'):
        build_embedder(config(mode, embedding_api_key=None))
    with pytest.raises(ValueError, match='embedding_base_url'):
        build_embedder(config(mode, embedding_base_url='https://user:secret@example.com'))
