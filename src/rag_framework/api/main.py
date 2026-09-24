"""FastAPI entry point for indexing and observable adaptive retrieval."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from rag_framework.config import settings
from rag_framework.core.models import Document, Query, RetrievalTrace
from rag_framework.pipeline.indexing import CharacterChunker, IndexingPipeline
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers import ChromaVectorStore, HashEmbedder, HeuristicQueryRouter


class IndexDocumentsRequest(BaseModel):
    documents: list[Document] = Field(min_length=1)


class IndexDocumentsResponse(BaseModel):
    indexed_documents: int
    indexed_chunks: int


vector_store = ChromaVectorStore(settings.chroma_directory, settings.chroma_collection)
embedder = HashEmbedder(settings.embedding_dimensions)
indexing_pipeline = IndexingPipeline(CharacterChunker(), embedder, vector_store)
retriever = AdaptiveRetriever(vector_store, embedder, HeuristicQueryRouter())

app = FastAPI(
    title="RAG Framework API",
    description="Provider-agnostic RAG control plane with adaptive retrieval traces.",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/v1/index/documents", response_model=IndexDocumentsResponse)
async def index_documents(request: IndexDocumentsRequest) -> IndexDocumentsResponse:
    chunks = await indexing_pipeline.index(request.documents)
    return IndexDocumentsResponse(indexed_documents=len(request.documents), indexed_chunks=len(chunks))


@app.post("/v1/retrieve", response_model=RetrievalTrace)
async def retrieve(query: Query) -> RetrievalTrace:
    return await retriever.retrieve(query)
