"""Default Chroma implementation of the vector-store port."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma

from rag_framework.contracts.providers import VectorStore
from rag_framework.core.models import Chunk, RetrievedChunk


class ChromaVectorStore(VectorStore):
    def __init__(self, persist_directory: Path, collection_name: str) -> None:
        # LangChain owns collection lifecycle; the framework still supplies precomputed
        # vectors so its VectorStore contract remains independent of any embedder.
        self._vector_store = Chroma(
            collection_name=collection_name,
            persist_directory=str(persist_directory),
            embedding_function=None,
        )
        self._collection = self._vector_store._collection

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Each chunk requires exactly one embedding")
        await asyncio.to_thread(self._upsert_sync, chunks, embeddings)

    def _upsert_sync(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self._collection.upsert(
            ids=[chunk.id for chunk in chunks],
            documents=[chunk.content for chunk in chunks],
            embeddings=embeddings,
            metadatas=[self._metadata(chunk) for chunk in chunks],
        )

    async def search(
        self, query_embedding: list[float], *, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]:
        result = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=filters or None,
            include=["documents", "metadatas", "distances"],
        )
        return self._to_results(result)

    async def clear(self) -> int:
        return await asyncio.to_thread(self._clear_sync)

    def _clear_sync(self) -> int:
        count = self._collection.count()
        # Reset collection also resets its fixed embedding dimension.
        self._vector_store.reset_collection()
        self._collection = self._vector_store._collection
        return count

    async def count(self) -> int:
        return await asyncio.to_thread(self._collection.count)

    async def health(self) -> bool:
        try:
            await self.count()
            return True
        except Exception:  # noqa: BLE001 - Health reports provider availability.
            return False

    async def close(self) -> None:
        # Chroma's embedded client is process-shared; stopping it breaks sibling collections.
        pass

    @staticmethod
    def _metadata(chunk: Chunk) -> dict[str, Any]:
        metadata = {key: value for key, value in chunk.metadata.items() if isinstance(value, (str, int, float, bool))}
        metadata.update({"document_id": chunk.document_id, "chunk_index": chunk.index, "source_uri": chunk.source_uri or ""})
        return metadata

    @staticmethod
    def _to_results(result: dict[str, Any]) -> list[RetrievedChunk]:
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [
            RetrievedChunk(
                chunk=Chunk(
                    id=chunk_id,
                    content=content,
                    document_id=metadata["document_id"],
                    index=metadata["chunk_index"],
                    source_uri=metadata.get("source_uri") or None,
                    metadata={key: value for key, value in metadata.items() if key not in {"document_id", "chunk_index", "source_uri"}},
                ),
                score=1 / (1 + distance),
                source="vector",
                rank=rank,
                component_scores={"vector": 1 / (1 + distance)},
            )
            for rank, (chunk_id, content, metadata, distance) in enumerate(
                zip(ids, documents, metadatas, distances), start=1
            )
        ]
