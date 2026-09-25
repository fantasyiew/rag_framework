"""Provider-agnostic ingestion and chunking pipeline."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag_framework.contracts.providers import Embedder, KeywordStore, VectorStore
from rag_framework.core.models import Chunk, Document


class CharacterChunker:
    def __init__(self, chunk_size: int = 800, overlap: int = 120) -> None:
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
        )

    def split(self, document: Document) -> list[Chunk]:
        parts = self._splitter.split_text(document.content.strip())
        return [
            Chunk(
                document_id=document.id,
                index=index,
                content=content,
                source_uri=document.source_uri,
                metadata=document.metadata,
            )
            for index, content in enumerate(parts)
        ]


class IndexingPipeline:
    def __init__(
        self,
        chunker: CharacterChunker,
        embedder: Embedder,
        vector_store: VectorStore,
        keyword_store: KeywordStore | None = None,
    ) -> None:
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store
        self.keyword_store = keyword_store

    async def index(self, documents: list[Document]) -> list[Chunk]:
        chunks = [chunk for document in documents for chunk in self.chunker.split(document)]
        if chunks:
            embeddings = await self.embedder.embed_documents([chunk.content for chunk in chunks])
            await self.vector_store.upsert(chunks, embeddings)
            if self.keyword_store is not None:
                await self.keyword_store.upsert(chunks)
        return chunks
