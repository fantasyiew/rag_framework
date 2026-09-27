from fastapi import APIRouter, HTTPException, Request

from .adapters import AdapterOptions
from .service import SourceService


def source_router(service: SourceService) -> APIRouter:
    router = APIRouter(prefix='/v1/sources', tags=['sources'])

    @router.post('')
    async def upload(request: Request, name: str, kind: str = 'text'):
        data = bytearray()
        async for part in request.stream():
            data.extend(part)
            if len(data) > 10_000_000:
                raise HTTPException(413, '文件不能超过 10 MB')
        try:
            return service.upload(bytes(data), name[:255], kind)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get('')
    async def sources():
        return service.list_sources()

    @router.get('/documents')
    async def documents():
        return service.list_documents()

    @router.get('/documents/{document_id}')
    async def document(document_id: str):
        try:
            return service.get_document(document_id)
        except KeyError as exc:
            raise HTTPException(404, 'Document 不存在或未纳入来源目录') from exc

    @router.get('/runs')
    async def runs():
        return service.list_runs()

    @router.post('/{source_id}/preview')
    async def preview(source_id: str, options: AdapterOptions):
        try:
            documents = service.prepare(source_id, options)
            return {'document_count': len(documents), 'documents': documents[:10]}
        except KeyError as exc:
            raise HTTPException(404, '数据源不存在') from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/{source_id}/ingest')
    async def ingest(source_id: str, options: AdapterOptions):
        try:
            return await service.ingest(source_id, options)
        except KeyError as exc:
            raise HTTPException(404, '数据源不存在') from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get('/{source_id}')
    async def detail(source_id: str):
        try:
            return service.get(source_id)
        except KeyError as exc:
            raise HTTPException(404, '数据源不存在') from exc

    return router
