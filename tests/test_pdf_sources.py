import io

import httpx
import pytest
from fastapi import FastAPI
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_sources import Pipeline

from rag_framework.sources.adapters import AdapterOptions, PdfAdapter
from rag_framework.sources.api import source_router
from rag_framework.sources.service import SourceService


def pdf_bytes(pages=('Hello PDF', None), encrypted=False):
    writer = PdfWriter()
    writer.add_metadata({'/Title': 'Test title'})
    for text in pages:
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                     NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({
                NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 20 200 Td ({text}) Tj ET'.encode())
            page[NameObject('/Contents')] = stream
    if encrypted:
        writer.encrypt('password')
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_text_metadata_and_empty_page_warning():
    adapter = PdfAdapter()
    data = pdf_bytes()
    assert adapter.inspect(data)['empty_pages'] == [2]
    assert adapter.inspect(data)['warnings']
    document = adapter.documents(data, AdapterOptions())[0]
    assert document.content == 'Hello PDF'
    assert document.metadata == {'source_type': 'pdf', 'page_number': 1,
                                 'page_count': 2, 'title': 'Test title'}


@pytest.mark.parametrize('data', [b'not pdf', b'%PDF-1.7\nbroken', pdf_bytes((None,)),
                                 pdf_bytes(encrypted=True)])
def test_pdf_rejects_invalid_empty_and_encrypted(data):
    with pytest.raises(ValueError):
        PdfAdapter().inspect(data)


@pytest.mark.parametrize(('attribute', 'limit'), [
    ('max_pages', 1), ('max_stream_bytes', 1), ('max_characters', 1),
])
def test_pdf_limits(attribute, limit, monkeypatch):
    monkeypatch.setattr(PdfAdapter, attribute, limit)
    with pytest.raises(ValueError):
        PdfAdapter().inspect(pdf_bytes())


async def test_pdf_api_archive_dedup_rebuild_and_invalid_upload(tmp_path):
    pipeline = Pipeline()
    service = SourceService(tmp_path, pipeline)
    app = FastAPI()
    app.include_router(source_router(service))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        bad = await client.post('/v1/sources?name=bad.pdf&kind=pdf', content=b'bad')
        assert bad.status_code == 422
        assert service.list_sources() == []
        upload = await client.post('/v1/sources?name=test.pdf&kind=pdf', content=pdf_bytes())
        assert upload.status_code == 200
        source_id = upload.json()['id']
        preview = await client.post(f'/v1/sources/{source_id}/preview', json={})
        assert preview.json()['documents'][0]['metadata']['page_number'] == 1
        first = await client.post(f'/v1/sources/{source_id}/ingest', json={})
        assert first.json()['created_documents'] == 1
        repeat = await client.post(f'/v1/sources/{source_id}/ingest', json={})
        assert repeat.json()['skipped_documents'] == 1
    restarted = SourceService(tmp_path, pipeline)
    before = restarted.list_documents()[0]
    await restarted.clear()
    assert (await restarted.rebuild())['status'] == 'complete'
    assert restarted.list_documents()[0]['id'] == before['id']
    assert restarted.list_documents()[0]['metadata']['page_number'] == 1
