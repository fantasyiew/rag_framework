import httpx
import pytest
from fastapi import FastAPI
from test_sources import Pipeline

from rag_framework.sources.adapters import AdapterOptions, CsvAdapter, MarkdownAdapter
from rag_framework.sources.api import source_router
from rag_framework.sources.service import SourceService


def test_csv_quoted_multiline_bom_and_metadata():
    data = '\ufeffname,body,id\r\nTower,"Hello, world\nsecond line",001\r\n'.encode()
    adapter = CsvAdapter()
    assert adapter.inspect(data)['record_count'] == 1
    document = adapter.documents(data, AdapterOptions(content_fields=['body']))[0]
    assert document.content == 'body: Hello, world\nsecond line'
    assert document.metadata['raw_metadata'] == {'name': 'Tower', 'id': '001'}
    assert document.metadata['source_type'] == 'csv'


@pytest.mark.parametrize('data', [
    b'a,a\nx,y', b'a,\nx,y', b'a,b\nx', b'a,b\nx,y,z',
    b'a,b', b'a,b\n"unfinished,x', b'\xff',
])
def test_csv_rejects_invalid_input(data):
    with pytest.raises(ValueError):
        CsvAdapter().inspect(data)


def test_csv_requires_nonempty_selected_content():
    for fields in ([], ['missing'], ['empty']):
        with pytest.raises(ValueError):
            CsvAdapter().documents(b'body,empty\nhello,', AdapterOptions(content_fields=fields))


def test_markdown_hierarchy_fences_and_line_positions():
    data = b'\n# Root\nintro\n### Deep\n~~~md\n# Not heading\n~~~\nbody\n## Sibling\ntext\n'
    docs = MarkdownAdapter().documents(data, AdapterOptions())
    assert len(docs) == 3
    assert docs[0].metadata['line_start'] == 3
    assert docs[0].metadata['line_end'] == 3
    assert docs[1].metadata['heading_path'] == ['Root', 'Deep']
    assert '# Not heading' in docs[1].content
    assert docs[2].metadata['heading_path'] == ['Root', 'Sibling']
    assert docs[2].metadata['line_start'] == 10


def test_markdown_setext_and_unclosed_fence():
    docs = MarkdownAdapter().documents(b'Title\n=====\nbody\nSub\n---\n```\n# code', AdapterOptions())
    assert docs[1].metadata['heading_path'] == ['Title', 'Sub']
    assert docs[1].content == '```\n# code'
    with pytest.raises(ValueError, match='正文'):
        MarkdownAdapter().inspect(b'# Title only')


@pytest.mark.parametrize(('kind', 'data', 'options'), [
    ('csv', b'body,id\nhello,001', {'content_fields': ['body']}),
    ('markdown', b'# Title\nhello', {}),
])
async def test_extension_upload_preview_ingest_restart_rebuild(tmp_path, kind, data, options):
    pipeline = Pipeline()
    service = SourceService(tmp_path, pipeline)
    app = FastAPI()
    app.include_router(source_router(service))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        upload = await client.post(f'/v1/sources?name=test&kind={kind}', content=data)
        assert upload.status_code == 200
        source_id = upload.json()['id']
        preview = await client.post(f'/v1/sources/{source_id}/preview', json=options)
        assert preview.status_code == 200
        assert preview.json()['document_count'] == 1
        first = await client.post(f'/v1/sources/{source_id}/ingest', json=options)
        assert first.json()['created_documents'] == 1
    restarted = SourceService(tmp_path, pipeline)
    repeat = restarted.upload(data, 'renamed', kind)
    assert (await restarted.ingest(repeat['id'], AdapterOptions(**options)))['skipped_documents'] == 1
    before = restarted.list_documents()
    await restarted.clear()
    assert (await restarted.rebuild())['status'] == 'complete'
    assert restarted.list_documents()[0]['id'] == before[0]['id']
    assert restarted.list_documents()[0]['metadata']['source_type'] == kind
