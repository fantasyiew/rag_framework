"""Embedded Qdrant backend; one isolated local directory per logical collection."""

import asyncio
import hashlib
import threading
from uuid import NAMESPACE_URL, uuid5

from rag_framework.contracts.providers import VectorStore
from rag_framework.core.models import Chunk, RetrievedChunk
from rag_framework.core.vectors import validate_vectors


class QdrantVectorStore(VectorStore):
    def __init__(self, directory, collection, dimensions):
        from qdrant_client import QdrantClient

        self.collection = collection
        self.dimensions = dimensions
        self.lock = threading.Lock()
        self.closed = False
        path = directory / hashlib.sha256(collection.encode()).hexdigest()
        self.client = QdrantClient(path=str(path))

    async def _run(self, operation):
        def guarded():
            with self.lock:
                if self.closed:
                    raise RuntimeError('Qdrant store is closed')
                return operation()
        return await asyncio.to_thread(guarded)

    async def upsert(self, chunks, embeddings):
        from qdrant_client import models

        validate_vectors(embeddings, len(chunks), self.dimensions)
        if not chunks:
            return

        def write():
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                    size=self.dimensions, distance=models.Distance.COSINE))
            self.client.upsert(self.collection, points=[models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, chunk.id)), vector=vector,
                payload={'chunk': chunk.model_dump(mode='json'), 'metadata': chunk.metadata},
            ) for chunk, vector in zip(chunks, embeddings, strict=True)], wait=True)
        await self._run(write)

    async def search(self, query_embedding, *, top_k, filters):
        from qdrant_client import models

        validate_vectors([query_embedding], 1, self.dimensions)
        if top_k < 1:
            raise ValueError('top_k must be positive')
        conditions = []
        for key, value in filters.items():
            if not key or any(c in key for c in '.$[]') or not isinstance(value, (str, int, bool)):
                raise ValueError('Qdrant supports flat string/integer/boolean equality filters only')
            conditions.append(models.FieldCondition(key='metadata.' + key,
                                                    match=models.MatchValue(value=value)))

        def read():
            if not self.client.collection_exists(self.collection):
                return []
            points = self.client.query_points(self.collection, query=query_embedding, limit=top_k,
                query_filter=models.Filter(must=conditions) if conditions else None,
                with_payload=True).points
            return [RetrievedChunk(chunk=Chunk.model_validate(point.payload['chunk']),
                score=point.score, rank=index, source='vector',
                component_scores={'vector': point.score}) for index, point in enumerate(points, 1)]
        return await self._run(read)

    def _count(self):
        return (self.client.count(self.collection, exact=True).count
                if self.client.collection_exists(self.collection) else 0)

    async def count(self):
        return await self._run(self._count)

    def snapshot_chunks(self):
        with self.lock:
            if not self.client.collection_exists(self.collection):
                return []
            chunks, offset = [], None
            while True:
                points, offset = self.client.scroll(self.collection, limit=256,
                    offset=offset, with_payload=True, with_vectors=False)
                chunks.extend(Chunk.model_validate(point.payload['chunk']) for point in points)
                if offset is None:
                    return chunks

    async def clear(self):
        def clear_collection():
            count = self._count()
            if self.client.collection_exists(self.collection):
                self.client.delete_collection(self.collection)
            return count
        return await self._run(clear_collection)

    async def health(self):
        try:
            await self.count()
            return True
        except Exception:  # noqa: BLE001 - Report availability without provider details.
            return False

    async def close(self):
        def close_client():
            with self.lock:
                if not self.closed:
                    self.client.close()
                    self.closed = True
        await asyncio.to_thread(close_client)
