import httpx
import pytest
from fastapi import FastAPI
from test_sources import Pipeline

from rag_framework.sources.adapters import AdapterOptions, HtmlAdapter
from rag_framework.sources.api import source_router
from rag_framework.sources.service import SourceService


def test_html_hierarchy_title_entities_and_blocks():
    data = b'<head><title>A &amp; B</title></head><h1>Root</h1><p>Hello <b>world</b>.</p><h3>Deep</h3><ul><li>One</li><li>Two</li></ul><h2>Next</h2><p>End</p>'
    docs = HtmlAdapter().documents(data, AdapterOptions())
    assert len(docs) == 3
    assert docs[0].content == 'Hello world.'
    assert docs[0].metadata['title'] == 'A & B'
    assert docs[1].metadata['heading_path'] == ['Root', 'Deep']
    assert docs[1].content == 'One\nTwo'
    assert docs[2].metadata['heading_path'] == ['Root', 'Next']


def test_html_does_not_include_active_content_or_attributes():
    data = b'<script>secret1</script><style>secret2</style><template><div>secret3</div></template><iframe src="http://localhost">secret4</iframe><p onclick="secret5">safe &lt;img&gt;</p><img src="http://localhost"><a href="http://localhost">link</a>'
    content = HtmlAdapter().documents(data, AdapterOptions())[0].content
    assert 'secret' not in content
    assert 'localhost' not in content
    assert content == 'safe <img>\nlink'


@pytest.mark.parametrize('data', [b'', b'\xff', b'<script>only script</script>',
                                 b'<head><title>Only title</title></head>', b'<h1>Only heading</h1>'])
def test_html_empty_or_invalid_rejected(data):
    with pytest.raises(ValueError):
        HtmlAdapter().inspect(data)


def test_html_fragment_unclosed_tags_and_self_closing_ignored_tag():
    docs = HtmlAdapter().documents(b'<script/><h1>Title<p>Hello<br>world', AdapterOptions())
    assert docs[0].content == 'Hello\nworld'
    assert docs[0].metadata['heading_path'] == ['Title']


async def test_html_api_archive_dedup_and_rebuild(tmp_path):
    pipeline = Pipeline()
    service = SourceService(tmp_path, pipeline)
    app = FastAPI()
    app.include_router(source_router(service))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/v1/sources?name=test.html&kind=html',
                                     content=b'<h1>Title</h1><p>Searchable text</p>')
        assert response.status_code == 200
        source_id = response.json()['id']
        preview = await client.post(f'/v1/sources/{source_id}/preview', json={})
        assert preview.json()['documents'][0]['metadata']['heading_path'] == ['Title']
        for field in ('created_documents', 'skipped_documents'):
            result = await client.post(f'/v1/sources/{source_id}/ingest', json={})
            assert result.json()[field] == 1
    restarted = SourceService(tmp_path, pipeline)
    before = restarted.list_documents()[0]
    await restarted.clear()
    assert (await restarted.rebuild())['status'] == 'complete'
    assert restarted.list_documents()[0]['id'] == before['id']
