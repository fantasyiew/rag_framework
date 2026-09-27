import io
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from rag_framework.pipeline.indexing import CharacterChunker
from rag_framework.sources.adapters import AdapterOptions, DocxAdapter, JsonAdapter
from rag_framework.sources.api import source_router
from rag_framework.sources.service import SourceService


class Pipeline:
    chunker = CharacterChunker()
    embedder = SimpleNamespace()

    def __init__(self):
        self.ids = set()
        self.fail = False
        self.vector_store = FakeStore(self)
        self.keyword_store = FakeStore(self)

    async def index(self, documents):
        chunks = [c for d in documents for c in self.chunker.split(d)]
        self.ids.update(c.id for c in chunks)
        if self.fail:
            raise RuntimeError('private provider error')
        return chunks


class FakeStore:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    async def clear(self):
        count = len(self.pipeline.ids)
        self.pipeline.ids.clear()
        return count

    async def count(self):
        return len(self.pipeline.ids)


def test_json_fields_metadata_and_nested_rejection():
    adapter = JsonAdapter()
    options = AdapterOptions(content_fields=['name'])
    documents = adapter.documents(b'[{"name":"tower","height":333}]', options)
    assert documents[0].content == 'name: tower'
    assert documents[0].metadata['raw_metadata'] == {'height': 333}
    assert not adapter.inspect(b'{"name":"tower","nested":{"a":1}}')['supported']
    with pytest.raises(ValueError, match='嵌套'):
        adapter.documents(b'{"name":"tower","nested":{"a":1}}', options)
    with pytest.raises(ValueError, match='没有正文'):
        adapter.documents(b'[{"name":"ok"},{"height":333}]', options)


def test_json_accepts_scalar_arrays_but_rejects_complex_arrays():
    adapter = JsonAdapter()
    data = b'{"name":"tower","keywords":["A","B","C"],"levels":[1,2,null]}'
    inspection = adapter.inspect(data)

    assert inspection['supported'] is True
    document = adapter.documents(
        data,
        AdapterOptions(content_fields=['name', 'keywords']),
    )[0]
    assert document.content == 'name: tower\nkeywords: A, B, C'
    assert document.metadata['raw_metadata'] == {'levels': [1, 2, None]}

    for invalid in (
        b'{"keywords":[{"name":"A"}]}',
        b'{"keywords":[["A"], ["B"]]}',
        b'{"keywords":["A", {"name":"B"}]}',
    ):
        result = adapter.inspect(invalid)
        assert result['supported'] is False
        assert result['nested_fields'] == ['keywords']


def test_docx_sections_keep_headings_and_positions():
    archive = io.BytesIO()
    xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Tokyo</w:t></w:r></w:p>
    <w:p><w:r><w:t>Tower text</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Hours</w:t></w:r></w:p>
    <w:p><w:r><w:t>Open daily</w:t></w:r></w:p></w:body></w:document>'''
    with zipfile.ZipFile(archive, 'w') as file:
        file.writestr('word/document.xml', xml)
    documents = DocxAdapter().documents(archive.getvalue(), AdapterOptions())
    assert len(documents) == 2
    assert documents[1].metadata['heading_path'] == ['Tokyo', 'Hours']
    assert documents[1].content == 'Open daily'
    assert documents[0].metadata['block_start'] == 1


async def test_repeat_uploads_and_restart_skip_successful_documents(tmp_path):
    pipeline = Pipeline()
    service = SourceService(tmp_path, pipeline)
    source = service.upload(b'hello world', 'one.txt', 'text')
    first = await service.ingest(source['id'], AdapterOptions())
    restarted = SourceService(tmp_path, pipeline)
    second_source = restarted.upload(b'hello world', 'renamed.txt', 'text')
    second = await restarted.ingest(second_source['id'], AdapterOptions())
    assert first['created_documents'] == 1
    assert second['skipped_documents'] == 1
    assert len(pipeline.ids) == 1
    assert len(restarted.list_documents()) == 1
    assert len(restarted.list_sources()) == 2
    assert len(restarted.list_runs()) == 2


async def test_failure_retry_keeps_stable_chunk_ids(tmp_path):
    pipeline = Pipeline()
    service = SourceService(tmp_path, pipeline)
    source = service.upload(b'hello', 'file.txt', 'text')
    pipeline.fail = True
    failed = await service.ingest(source['id'], AdapterOptions())
    assert failed['status'] == 'failed'
    assert failed['error'] == 'RuntimeError'
    assert not service.list_documents()
    pipeline.fail = False
    result = await service.ingest(source['id'], AdapterOptions())
    assert result['created_documents'] == 1
    assert len(pipeline.ids) == 1


async def test_json_raw_metadata_is_durable_but_not_repeated_on_chunks(tmp_path):
    pipeline = Pipeline()
    service = SourceService(tmp_path, pipeline)
    source = service.upload(b'{"name":"Tower","city":"Tokyo"}', 'file.json', 'json')
    options = AdapterOptions(content_fields=['name'])
    preview = service.prepare(source['id'], options)
    await service.ingest(source['id'], options)
    assert service.list_documents()[0]['metadata']['raw_metadata'] == {'city': 'Tokyo'}
    assert 'raw_metadata' not in pipeline.chunker.split(preview[0])[0].metadata


async def test_clear_preserves_sources_and_runs_then_rebuilds(tmp_path):
    pipeline = Pipeline()
    service = SourceService(tmp_path, pipeline)
    source = service.upload(b'preserved source', 'source.txt', 'text')
    await service.ingest(source['id'], AdapterOptions())

    cleared = await service.clear()
    assert cleared['deleted_documents'] == 1
    assert service.stats() == {'sources': 1, 'documents': 0, 'runs': 2}
    assert (tmp_path / source['id']).read_bytes() == b'preserved source'

    rebuilt = await service.rebuild()
    assert rebuilt['status'] == 'complete'
    assert rebuilt['documents'] == 1
    assert len(service.list_sources()) == 1


async def test_source_api_inspect_preview_ingest_and_history(tmp_path):
    app = FastAPI()
    app.include_router(source_router(SourceService(tmp_path, Pipeline())))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/v1/sources?name=test.json&kind=json',
                                     content=b'{"body":"hello","count":2}')
        assert response.status_code == 200
        source_id = response.json()['id']
        options = {'content_fields': ['body']}
        preview = await client.post(f'/v1/sources/{source_id}/preview', json=options)
        assert preview.json()['documents'][0]['metadata']['raw_metadata'] == {'count': 2}
        first = await client.post(f'/v1/sources/{source_id}/ingest', json=options)
        second = await client.post(f'/v1/sources/{source_id}/ingest', json=options)
        assert first.json()['created_documents'] == 1
        assert second.json()['skipped_documents'] == 1
        documents = (await client.get('/v1/sources/documents')).json()
        detail = await client.get(f'/v1/sources/documents/{documents[0]["id"]}')
        assert detail.json()['metadata']['raw_metadata'] == {'count': 2}
        assert len((await client.get('/v1/sources/runs')).json()) == 2
        assert (await client.get('/v1/sources/documents/missing')).status_code == 404
        assert (await client.post('/v1/sources/missing/preview', json={})).status_code == 404
