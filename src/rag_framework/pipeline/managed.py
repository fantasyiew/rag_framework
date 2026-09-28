"""Index safety boundaries used by the composed service, independent of backend."""

from rag_framework.contracts.lifecycle import StrictIndexWriter
from rag_framework.core.models import Document
from rag_framework.core.vectors import validate_vectors
from rag_framework.index_state import IndexCompatibilityError, IndexState
from rag_framework.pipeline.indexing import IndexingPipeline
from rag_framework.pipeline.retrieval import AdaptiveRetriever


class ManagedIndexingPipeline(IndexingPipeline):
    def __init__(self, *args, state: IndexState, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = state

    async def check_index(self):
        async with self.state.lock:
            await self.state.validate()

    def canonical_documents(self):
        return self.state.documents()

    async def _write(self, documents):
        chunks = [chunk for document in documents for chunk in self.chunker.split(document)]
        if chunks:
            embeddings = validate_vectors(
                await self.embedder.embed_documents([chunk.content for chunk in chunks]),
                len(chunks), self.state.fingerprint["embedding"]["dimensions"],
            )
            await self.vector_store.upsert(chunks, embeddings)
            if self.keyword_store is not None:
                if isinstance(self.keyword_store, StrictIndexWriter):
                    await self.keyword_store.upsert_strict(chunks)
                else:
                    await self.keyword_store.upsert(chunks)
        return chunks

    async def index(self, documents: list[Document]):
        async with self.state.lock:
            await self.state.validate()
            if not documents:
                return []
            self.state.begin("index", documents)
            try:
                chunks = await self._write(documents)
                self.state.complete()
                return chunks
            except Exception as exc:
                self.state.fail(exc)
                raise

    async def rebuild_documents(self, documents: list[Document]):
        async with self.state.lock:
            # Include direct writes committed between source preflight and this lock acquisition.
            latest = {document.id: document for document in documents}
            latest.update({document.id: document for document in self.state.documents()})
            documents = list(latest.values())
            if not documents and (await self.vector_store.count() or await self.keyword_store.count()):
                raise IndexCompatibilityError("没有可恢复的 Document，拒绝空重建；请提供原始数据")
            self.state.begin("rebuild", documents)
            try:
                await self.vector_store.clear()
                await self.keyword_store.clear()
                chunks = await self._write(documents)
                self.state.complete()
                return chunks
            except Exception as exc:
                self.state.fail(exc)
                raise

    async def clear_index(self):
        async with self.state.lock:
            self.state.begin("clear", [])
            try:
                vector_count = await self.vector_store.clear()
                keyword_count = await self.keyword_store.clear()
                self.state.complete()
                return vector_count, keyword_count
            except Exception as exc:
                self.state.fail(exc)
                raise


class ManagedRetriever(AdaptiveRetriever):
    def __init__(self, *args, state: IndexState, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = state

    async def retrieve(self, query):
        # Serialize against writes/rebuilds; no request sees a half-built index.
        async with self.state.lock:
            await self.state.validate()
            return await super().retrieve(query)

    async def _vector_search_without_trace(self, query, top_k, filters):
        vector = validate_vectors([await self.embedder.embed_query(query)], 1,
                                  self.state.fingerprint["embedding"]["dimensions"])[0]
        return await self.vector_store.search(vector, top_k=top_k, filters=filters)
