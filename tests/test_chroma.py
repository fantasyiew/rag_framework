from pathlib import Path

import pytest

from rag_framework.core.models import Chunk, Document, Query
from rag_framework.pipeline.indexing import CharacterChunker, IndexingPipeline
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers.bm25 import InMemoryBM25KeywordStore
from rag_framework.providers.chroma import ChromaVectorStore
from rag_framework.providers.hash_embedder import HashEmbedder
from rag_framework.providers.router import HeuristicQueryRouter


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
    assert await store.count() == 1
    assert await store.clear() == 1
    assert await store.count() == 0


@pytest.mark.asyncio
async def test_real_indexing_and_hybrid_retrieval_pipeline(tmp_path: Path) -> None:
    vector_store = ChromaVectorStore(tmp_path, "hybrid-documents")
    keyword_store = InMemoryBM25KeywordStore()
    embedder = HashEmbedder()
    indexing = IndexingPipeline(
        CharacterChunker(chunk_size=100, overlap=10),
        embedder,
        vector_store,
        keyword_store,
    )
    retriever = AdaptiveRetriever(
        vector_store,
        embedder,
        HeuristicQueryRouter(),
        keyword_store,
    )
    await indexing.index(
        [
            Document(content="BM25 keyword retrieval finds exact terms."),
            Document(content="Vector retrieval finds semantic relationships."),
        ]
    )

    trace = await retriever.retrieve(Query(text="BM25 retrieval"))

    assert trace.plan is not None
    assert trace.plan.strategy.value == "hybrid"
    assert trace.final_context[0].source == "hybrid"
    assert {step.name for step in trace.steps} >= {"hybrid_recall", "rrf_fusion"}
