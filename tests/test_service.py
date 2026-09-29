from unittest.mock import AsyncMock

import pytest

from rag_framework.config import Settings
from rag_framework.core.models import Document
from rag_framework.service import build_service


@pytest.mark.parametrize('backend', ['chroma', 'qdrant'])
async def test_runtime_isolates_knowledge_bases_and_closes_once(tmp_path, backend):
    if backend == 'qdrant':
        pytest.importorskip('qdrant_client')
    config = Settings(
        _env_file=None, query_planner_mode='heuristic', answer_generator_mode='extractive',
        vector_backend=backend, qdrant_directory=tmp_path / 'qdrant',
        evaluation_judge_mode='heuristic', reranker_mode='disabled', keyword_backend='memory',
        chroma_directory=tmp_path / 'chroma', source_directory=tmp_path / 'sources',
        knowledge_base_directory=tmp_path / 'bases',
        evaluation_report_directory=tmp_path / 'reports',
        evaluation_dataset_directory=tmp_path / 'datasets',
    )
    service = build_service(config)
    default = service.knowledge_bases.runtime('default')
    other_id = service.knowledge_bases.create('Other').id
    other = service.knowledge_bases.runtime(other_id)
    await default.indexing_pipeline.index([Document(content='Only in default')])
    assert await default.vector_store.count() == 1
    assert await other.vector_store.count() == 0
    assert default.sources.directory == config.source_directory
    assert other.sources.directory != default.sources.directory
    assert default.retriever.planner is other.retriever.planner
    assert service.retrieval_evaluator(other_id).retriever is other.retriever
    from rag_framework.evaluation import RetrievalEvaluationRequest
    report = await service.retrieval_evaluator(other_id).evaluate(
        RetrievalEvaluationRequest(
            knowledge_base_id=other_id,
            cases=[{"query": {"text": "nothing"}, "relevant_chunk_ids": ["missing"]}],
        )
    )
    assert report.knowledge_base_id == other_id
    assert report.config_snapshot["config_hash"] == service.audit_snapshot()["config_hash"]
    assert service.evaluation_store.get(report.id).config_snapshot == report.config_snapshot
    close = AsyncMock()
    default.keyword_store.close = close
    await service.close()
    await service.close()
    close.assert_awaited_once()
