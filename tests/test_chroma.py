from pathlib import Path

import pytest

from rag_framework.core.models import Chunk
from rag_framework.providers.chroma import ChromaVectorStore
from rag_framework.providers.hash_embedder import HashEmbedder


@pytest.mark.asyncio
async def test_chroma_store_upserts_and_retrieves_chunk(tmp_path: Path) -> None:
    store = ChromaVectorStore(tmp_path, "test-documents")
    embedder = HashEmbedder()
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        index=0,
        content="Retrieval traces make RAG performance observable.",
        metadata={"team": "platform"},
    )

    await store.upsert([chunk], await embedder.embed_documents([chunk.content]))
    results = await store.search(await embedder.embed_query("observable retrieval"), top_k=1, filters={})

    assert results[0].chunk.id == "chunk-1"
    assert results[0].chunk.document_id == "doc-1"
    assert results[0].chunk.metadata == {"team": "platform"}
