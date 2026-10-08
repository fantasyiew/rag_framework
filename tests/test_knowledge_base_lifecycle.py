import json
from unittest.mock import AsyncMock

import pytest
from test_index_safety import config

from rag_framework.core.models import Document, Query
from rag_framework.hot_runtime import prepare_update
from rag_framework.index_state import IndexCompatibilityError
from rag_framework.knowledge_bases.bindings import embedding_profile
from rag_framework.service import build_service


async def test_profiles_persist_and_hot_updates_keep_per_base_embeddings(tmp_path):
    service = build_service(config(tmp_path))
    manager = service.knowledge_bases
    await manager.runtime('default').indexing_pipeline.index([Document(content='alpha')])
    other = manager.create('other', embedding_profile(config(tmp_path, embedding_dimensions=32)))
    runtime = manager.runtime(other.id)
    await runtime.indexing_pipeline.index([Document(content='beta')])
    prepare_update(service, service.settings.model_copy(update={'default_top_k': 3}))()
    assert manager.runtime(other.id).retriever.embedder is runtime.embedder
    assert manager.runtime('default').retriever.embedder is not runtime.embedder
    await service.close()
    second = build_service(config(tmp_path, embedding_dimensions=64))
    assert second.knowledge_bases.runtime('default').index_state.fingerprint['embedding']['dimensions'] == 16
    assert second.knowledge_bases.runtime(other.id).index_state.fingerprint['embedding']['dimensions'] == 32
    assert len((await second.knowledge_bases.runtime(other.id).retriever.retrieve(Query(text='beta'))).final_context) == 1
    await second.close()


@pytest.mark.parametrize('backend', ['chroma', 'qdrant'])
async def test_explicit_binding_rebuild_preserves_sources(tmp_path, backend):
    if backend == 'qdrant':
        pytest.importorskip('qdrant_client')
    service = build_service(config(tmp_path, vector_backend=backend, qdrant_directory=tmp_path / 'qdrant'))
    manager = service.knowledge_bases
    key = manager.create('migration').id
    old = manager.runtime(key)
    await old.indexing_pipeline.index([Document(content='recoverable alpha')])
    profile = embedding_profile(config(tmp_path, embedding_dimensions=32))
    with pytest.raises(ValueError, match='重建'):
        await manager.bind(key, profile)
    assert manager.runtime(key) is old
    result = await manager.bind(key, profile, rebuild=True)
    assert result['rebuild']['status'] == 'complete', result
    current = manager.runtime(key)
    assert current.index_state.fingerprint['embedding']['dimensions'] == 32
    assert len((await current.retriever.retrieve(Query(text='alpha'))).final_context) == 1
    with pytest.raises(IndexCompatibilityError):
        await old.indexing_pipeline.index([Document(content='stale')])
    current.embedder.embed_documents = AsyncMock(side_effect=RuntimeError('secret'))
    assert (await current.sources.rebuild())['status'] == 'failed'
    assert len(current.indexing_pipeline.canonical_documents()) == 1
    await service.close()


async def test_archive_restore_delete_are_isolated_and_confirmed(tmp_path):
    service = build_service(config(tmp_path))
    manager = service.knowledge_bases
    item = manager.create('disposable')
    runtime = manager.runtime(item.id)
    await runtime.indexing_pipeline.index([Document(content='alpha')])
    await manager.runtime('default').indexing_pipeline.index([Document(content='keep')])
    await manager.set_archived(item.id, True)
    assert (await manager.describe(item.id))['status'] == 'archived'
    with pytest.raises(IndexCompatibilityError):
        manager.runtime(item.id)
    with pytest.raises(IndexCompatibilityError):
        await runtime.retriever.retrieve(Query(text='alpha'))
    await manager.set_archived(item.id, False)
    assert await manager.runtime(item.id).vector_store.count() == 1
    with pytest.raises(ValueError):
        await manager.delete(item.id, 'wrong name')
    assert manager.get(item.id).status == 'active'
    assert (await manager.delete(item.id, item.name))['traces_preserved']
    assert manager.get(item.id).status == 'deleted'
    assert not (manager.directory / item.id).exists()
    assert item.id not in {base.id for base in manager.list()}
    assert await manager.runtime('default').vector_store.count() == 1
    with pytest.raises(ValueError):
        await manager.delete('default', '默认知识库')
    with pytest.raises(ValueError):
        await manager.set_archived('default', True)
    await service.close()


async def test_keys_are_references_and_missing_credentials_keep_admin_available(tmp_path):
    service = build_service(config(tmp_path, embedding_api_key='private-token'))
    item = service.knowledge_bases.create('keys')
    assert 'private-token' not in json.dumps(service.knowledge_bases.bindings.get(item.id))
    with pytest.raises(ValueError):
        service.knowledge_bases.create('bad', {'settings': {'embedding_api_key': 'bad'}})
    remote = embedding_profile(config(tmp_path, embedding_mode='compatible', embedding_model='remote',
                                      embedding_base_url='https://example.test/v1', embedding_api_key='private-token'))
    remote['secret_refs'] = {'embedding_api_key': 'MISSING_TEST_KEY'}
    unavailable = service.knowledge_bases.create('no credentials', remote)
    assert (await service.knowledge_bases.describe(unavailable.id))['index']['status'] == 'blocked'
    with pytest.raises(IndexCompatibilityError):
        await service.knowledge_bases.runtime(unavailable.id).retriever.retrieve(Query(text='alpha'))
    await service.close()


async def test_lifecycle_api_and_archived_read_only_access(tmp_path):
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from rag_framework.knowledge_bases.api import knowledge_base_router

    service = build_service(config(tmp_path))
    app = FastAPI()
    app.include_router(knowledge_base_router(service.knowledge_bases))

    @app.exception_handler(IndexCompatibilityError)
    async def incompatible(request, exc):
        return JSONResponse(status_code=409, content={'detail': str(exc)})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        item = (await client.post('/v1/knowledge-bases', json={'name': 'api test'})).json()
        path = '/v1/knowledge-bases/' + item['id']
        assert item['embedding_binding']['settings']['embedding_dimensions'] == 16
        assert (await client.post(path + '/archive')).status_code == 200
        assert (await client.get(path + '/sources')).status_code == 200
        assert (await client.get(path + '/runs')).status_code == 200
        assert (await client.post(path + '/clear')).status_code == 409
        assert (await client.post(path + '/restore')).status_code == 200
        profile = embedding_profile(config(tmp_path, embedding_dimensions=32))
        bound = await client.post(path + '/embedding-binding', json={'profile': profile, 'rebuild': True})
        assert bound.status_code == 200
        assert bound.json()['embedding_binding']['settings']['embedding_dimensions'] == 32
        assert (await client.request('DELETE', path, json={'confirmation_name': 'wrong'})).status_code == 422
        assert (await client.request('DELETE', path, json={'confirmation_name': 'api test'})).status_code == 200
        assert (await client.get(path)).status_code == 404
        assert (await client.get(path + '/runs')).status_code == 404
    await service.close()


async def test_legacy_model_is_not_guessed_and_matching_binding_needs_no_rebuild(tmp_path):
    first = build_service(config(tmp_path))
    await first.knowledge_bases.runtime('default').indexing_pipeline.index([Document(content='legacy alpha')])
    first.knowledge_bases.bindings.delete('default')
    await first.close()
    second = build_service(config(tmp_path, embedding_dimensions=32))
    description = await second.knowledge_bases.describe('default')
    assert description['embedding_binding'] is None
    assert description['index']['status'] == 'blocked'
    bound = await second.knowledge_bases.bind('default', embedding_profile(config(tmp_path)))
    assert bound['index']['status'] == 'ready'
    assert second.embedder is second.knowledge_bases.runtime('default').embedder
    assert len((await second.knowledge_bases.runtime('default').retriever.retrieve(Query(text='alpha'))).final_context) == 1
    await second.close()
