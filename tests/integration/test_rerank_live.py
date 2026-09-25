import os

import pytest

from rag_framework.config import Settings
from rag_framework.core.models import Chunk, RetrievedChunk
from rag_framework.providers.rerank import CloudReranker, CrossEncoderReranker


@pytest.mark.integration
@pytest.mark.asyncio
async def test_local_cross_encoder():
    model = os.getenv("RAG_TEST_RERANK_MODEL")
    if not model:
        pytest.skip("Set RAG_TEST_RERANK_MODEL to a cached CrossEncoder model or local path")
    pytest.importorskip("sentence_transformers")
    candidates = [RetrievedChunk(
        chunk=Chunk(id=str(i), document_id=str(i), index=0, content=text),
        score=1, source="test", rank=i+1,
    ) for i, text in enumerate(["Bananas are yellow.", "Tokyo Tower is 333 meters tall."])]
    results = await CrossEncoderReranker(model).rerank("How tall is Tokyo Tower?", candidates)
    assert results[0].chunk.id == "1"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cloud_reranker():
    if os.getenv("RAG_RUN_LIVE_RERANK") != "1":
        pytest.skip("Set RAG_RUN_LIVE_RERANK=1 to call the configured cloud reranker")
    settings = Settings()
    url = os.getenv("RAG_TEST_RERANK_CLOUD_URL") or settings.reranker_cloud_url
    configured_key = settings.reranker_cloud_api_key or settings.planner_api_key
    api_key = os.getenv("RAG_TEST_RERANK_CLOUD_API_KEY") or (
        configured_key.get_secret_value() if configured_key else None
    )
    if not url or not api_key:
        pytest.skip("Configure the cloud reranker URL and API key")
    reranker = CloudReranker(
        url=url,
        api_key=api_key,
        model_name=os.getenv("RAG_TEST_RERANK_CLOUD_MODEL", settings.reranker_cloud_model),
        protocol=os.getenv("RAG_TEST_RERANK_CLOUD_PROTOCOL", settings.reranker_cloud_protocol),
        timeout=settings.reranker_cloud_timeout,
    )
    candidates = [RetrievedChunk(
        chunk=Chunk(id=str(i), document_id=str(i), index=0, content=text),
        score=1, source="test", rank=i+1,
    ) for i, text in enumerate(["Bananas are yellow.", "Tokyo Tower is 333 meters tall."])]
    try:
        results = await reranker.rerank("How tall is Tokyo Tower?", candidates)
        assert results[0].chunk.id == "1"
    finally:
        await reranker.close()
