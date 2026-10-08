import hashlib
import io
import json
import zipfile

import httpx
import pytest
from fastapi import FastAPI
from test_index_safety import config

from rag_framework.core.models import Chunk, Document
from rag_framework.knowledge_bases.api import knowledge_base_router
from rag_framework.service import build_service


@pytest.mark.parametrize('backend', ['chroma', 'qdrant'])
async def test_zip_export_and_isolation(tmp_path, backend):
    if backend == 'qdrant':
        pytest.importorskip('qdrant_client')
    service = build_service(config(tmp_path, vector_backend=backend, qdrant_directory=tmp_path / 'qdrant'))
    try:
        manager = service.knowledge_bases
        key = manager.create('export-test').id
        runtime = manager.runtime(key)
        await runtime.indexing_pipeline.index([Document(id='document', content='日本旅游数据',
            source_uri='source://example', metadata={'raw_metadata': '{"keywords":["A","B"]}', 'title': '标题'})])
        await manager.runtime('default').indexing_pipeline.index([Document(content='other knowledge base')])
        expected = runtime.vector_store.snapshot_chunks()
        app = FastAPI()
        app.include_router(knowledge_base_router(manager))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get(f'/v1/knowledge-bases/{key}/export-chunks')
            assert response.status_code == 200
            assert response.headers['content-type'] == 'application/zip'
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                assert set(archive.namelist()) == {'chunks.jsonl', 'manifest.json'}
                data = archive.read('chunks.jsonl')
                rows = [json.loads(line) for line in data.splitlines()]
                manifest = json.loads(archive.read('manifest.json'))
                expected_rows = [chunk.model_dump(mode='json') for chunk in expected]
                for row in expected_rows:
                    row['metadata']['raw_metadata'] = '{"keywords":["A","B"]}'
                assert rows == expected_rows
                assert manifest['knowledge_base']['id'] == key
                assert manifest['chunk_count'] == len(rows) == 1
                assert manifest['includes_vectors'] is False
                assert manifest['chunks_sha256'] == hashlib.sha256(data).hexdigest()
                assert 'api_key' not in archive.read('manifest.json').decode()
                assert 'other knowledge base' not in data.decode()
                assert 'raw_metadata' in rows[0]['metadata']
            empty = manager.create('empty').id
            response = await client.get(f'/v1/knowledge-bases/{empty}/export-chunks')
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                assert archive.read('chunks.jsonl') == b''
                assert json.loads(archive.read('manifest.json'))['chunk_count'] == 0
            assert (await client.get('/v1/knowledge-bases/missing/export-chunks')).status_code == 404
        assert await runtime.vector_store.count() == 1
    finally:
        await service.close()


@pytest.mark.parametrize('backend', ['chroma', 'qdrant'])
async def test_paged_iteration(tmp_path, backend):
    if backend == 'qdrant':
        pytest.importorskip('qdrant_client')
    service = build_service(config(tmp_path, vector_backend=backend, qdrant_directory=tmp_path / 'qdrant'))
    try:
        store = service.knowledge_bases.runtime('default').vector_store
        chunks = [Chunk(id=f'chunk-{i}', document_id='doc', index=i, content=f'text-{i}') for i in range(5)]
        await store.upsert(chunks, [[1.0] * 16 for _ in chunks])
        exported = [chunk async for chunk in store.iter_chunks(page_size=2)]
        assert {chunk.id for chunk in exported} == {chunk.id for chunk in chunks}
        assert len(exported) == 5
    finally:
        await service.close()


async def test_export_waits_for_index_write_lock(tmp_path):
    import asyncio

    from rag_framework.knowledge_bases.export import prepare_export
    service = build_service(config(tmp_path))
    runtime = service.knowledge_bases.runtime('default')
    try:
        async with runtime.index_state.lock:
            task = asyncio.create_task(prepare_export(service.knowledge_bases, 'default'))
            await asyncio.sleep(0.05)
            assert not task.done()
        archive = await task
        archive.close()
    finally:
        await service.close()
