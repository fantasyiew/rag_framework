from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field

from rag_framework.sources.adapters import AdapterOptions

from .service import KnowledgeBaseManager


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    embedding_binding: dict | None = None


class BindRequest(BaseModel):
    profile: dict
    rebuild: bool = False


class DeleteRequest(BaseModel):
    confirmation_name: str


def knowledge_base_router(manager: KnowledgeBaseManager) -> APIRouter:
    router = APIRouter(prefix="/v1/knowledge-bases", tags=["knowledge-bases"])

    def runtime(knowledge_base_id: str, read_only: bool = False):
        try:
            if read_only:
                if manager.get(knowledge_base_id).status == 'deleted':
                    raise KeyError(knowledge_base_id)
                return manager._load_runtime(knowledge_base_id)
            return manager.runtime(knowledge_base_id)
        except KeyError as exc:
            raise HTTPException(404, "知识库不存在") from exc

    @router.get("")
    async def list_knowledge_bases():
        return [await manager.describe(item.id) for item in manager.list()]

    @router.post("")
    async def create_knowledge_base(request: CreateKnowledgeBaseRequest):
        try:
            return await manager.describe(manager.create(request.name, request.embedding_binding).id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    async def action(operation):
        try:
            return await operation
        except KeyError as exc:
            raise HTTPException(404, '知识库不存在') from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/{knowledge_base_id}/archive')
    async def archive(knowledge_base_id: str):
        return await action(manager.set_archived(knowledge_base_id, True))

    @router.post('/{knowledge_base_id}/restore')
    async def restore(knowledge_base_id: str):
        return await action(manager.set_archived(knowledge_base_id, False))

    @router.post('/{knowledge_base_id}/embedding-binding')
    async def bind(knowledge_base_id: str, request: BindRequest):
        return await action(manager.bind(knowledge_base_id, request.profile, request.rebuild))

    @router.delete('/{knowledge_base_id}')
    async def delete(knowledge_base_id: str, request: DeleteRequest):
        return await action(manager.delete(knowledge_base_id, request.confirmation_name))

    @router.get("/{knowledge_base_id}")
    async def get_knowledge_base(knowledge_base_id: str):
        try:
            return await manager.describe(knowledge_base_id)
        except KeyError as exc:
            raise HTTPException(404, "知识库不存在") from exc

    @router.post("/{knowledge_base_id}/clear")
    async def clear_knowledge_base(knowledge_base_id: str):
        result = await runtime(knowledge_base_id).sources.clear()
        return {**result, "knowledge_base_id": knowledge_base_id}

    @router.get('/{knowledge_base_id}/export-chunks')
    async def export_chunks(knowledge_base_id: str):
        from .export import prepare_export, stream_archive
        try:
            archive = await prepare_export(manager, knowledge_base_id)
        except KeyError:
            raise HTTPException(404, '知识库不存在') from None
        except NotImplementedError:
            raise HTTPException(501, '当前向量后端尚未实现 Chunk 导出') from None
        except Exception:  # noqa: BLE001 - Storage errors may contain sensitive details.
            raise HTTPException(503, 'Chunk 导出失败，请检查存储服务；未生成不完整下载包') from None
        return StreamingResponse(stream_archive(archive), media_type='application/zip',
            headers={'Content-Disposition': f'attachment; filename="chunks-{knowledge_base_id}.zip"'},
            background=BackgroundTask(archive.close))

    @router.post("/{knowledge_base_id}/rebuild")
    async def rebuild_knowledge_base(knowledge_base_id: str):
        result = await runtime(knowledge_base_id).sources.rebuild()
        return {**result, "knowledge_base_id": knowledge_base_id}

    @router.post("/{knowledge_base_id}/sources")
    async def upload_source(knowledge_base_id: str, request: Request, name: str, kind: str = "text"):
        data = bytearray()
        async for part in request.stream():
            data.extend(part)
            if len(data) > 10_000_000:
                raise HTTPException(413, "文件不能超过 10 MB")
        try:
            return runtime(knowledge_base_id).sources.upload(bytes(data), name[:255], kind)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/{knowledge_base_id}/sources")
    async def list_sources(knowledge_base_id: str):
        return runtime(knowledge_base_id, True).sources.list_sources()

    @router.get("/{knowledge_base_id}/documents")
    async def list_documents(knowledge_base_id: str):
        return runtime(knowledge_base_id, True).sources.list_documents()

    @router.get("/{knowledge_base_id}/documents/{document_id}")
    async def get_document(knowledge_base_id: str, document_id: str):
        try:
            return runtime(knowledge_base_id, True).sources.get_document(document_id)
        except KeyError as exc:
            raise HTTPException(404, "Document 不存在或未纳入来源目录") from exc

    @router.get("/{knowledge_base_id}/runs")
    async def list_runs(knowledge_base_id: str):
        return runtime(knowledge_base_id, True).sources.list_runs()

    @router.post("/{knowledge_base_id}/sources/{source_id}/preview")
    async def preview(knowledge_base_id: str, source_id: str, options: AdapterOptions):
        try:
            documents = runtime(knowledge_base_id).sources.prepare(source_id, options)
            return {"document_count": len(documents), "documents": documents[:10]}
        except KeyError as exc:
            raise HTTPException(404, "数据源不存在") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/{knowledge_base_id}/sources/{source_id}/ingest")
    async def ingest(knowledge_base_id: str, source_id: str, options: AdapterOptions):
        try:
            return await runtime(knowledge_base_id).sources.ingest(source_id, options)
        except KeyError as exc:
            raise HTTPException(404, "数据源不存在") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return router
