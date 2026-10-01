import pytest
from test_hot_config import config
from test_retrieval import StubEmbedder, StubRouter, StubVectorStore, make_result

from rag_framework.core.models import Document, Query, RetrievalStrategy
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers.bm25 import InMemoryBM25KeywordStore
from rag_framework.service import build_service


async def test_hybrid_removes_routing_filter_and_preserves_metadata_filter():
    class Router(StubRouter):
        async def plan(self, query):
            plan = await super().plan(query)
            plan.analysis.filters = {'knowledge_base_id': 'kb', 'city': 'Tokyo'}
            return plan

    class Vector(StubVectorStore):
        async def search(self, query_embedding, *, top_k, filters):
            assert filters == {'city': 'Tokyo'}
            return await super().search(query_embedding, top_k=top_k, filters=filters)

    result = make_result('useful')
    result.chunk.metadata['city'] = 'Tokyo'
    keyword = InMemoryBM25KeywordStore()
    await keyword.upsert([result.chunk])
    retriever = AdaptiveRetriever(Vector([result]), StubEmbedder(),
        Router(RetrievalStrategy.HYBRID), keyword)
    trace = await retriever.retrieve(Query(text='keyword evidence', knowledge_base_id='kb'))
    assert trace.final_context
    step = next(step for step in trace.steps if step.name == 'sanitize_filters')
    assert step.details['removed_fields'] == ['knowledge_base_id']


@pytest.mark.parametrize('backend', ['chroma', 'qdrant'])
async def test_keyword_restored_after_restart_but_not_after_clear(tmp_path, backend):
    if backend == 'qdrant':
        pytest.importorskip('qdrant_client')
    settings = config(tmp_path).model_copy(update={'vector_backend': backend,
                                                  'qdrant_directory': tmp_path / 'qdrant'})
    first = build_service(settings)
    kb = first.knowledge_bases.create('data').id
    runtime = first.knowledge_bases.runtime(kb)
    await runtime.indexing_pipeline.index([Document(content='Tokyo useful evidence')])
    await first.close()
    second = build_service(settings)
    try:
        runtime = second.knowledge_bases.runtime(kb)
        assert await runtime.keyword_store.count() == await runtime.vector_store.count() == 1
        assert await runtime.keyword_store.search('Tokyo', top_k=2, filters={})
        assert await second.knowledge_bases.runtime('default').keyword_store.count() == 0
        await runtime.indexing_pipeline.clear_index()
    finally:
        await second.close()
    third = build_service(settings)
    try:
        runtime = third.knowledge_bases.runtime(kb)
        assert await runtime.keyword_store.count() == 0
        assert await runtime.vector_store.count() == 0
    finally:
        await third.close()
