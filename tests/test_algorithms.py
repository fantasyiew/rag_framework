import pytest

from rag_framework.config import Settings
from rag_framework.contracts.providers import Chunker, Fusion
from rag_framework.core.models import Chunk, Document, Query
from rag_framework.providers.algorithm_factory import (
    AlgorithmRegistry,
    build_chunker,
    build_fusion,
)
from rag_framework.providers.planner_factory import build_query_planner
from rag_framework.service import build_service
from rag_framework.sources.adapters import AdapterOptions


def test_configuration_validation_and_legacy_precedence():
    old = Settings(_env_file=None, rrf_rank_constant=12)
    assert build_fusion(old).parameters == {"rank_constant": 12}
    new = Settings(_env_file=None, rrf_rank_constant=12, fusion_rank_constant=0)
    assert build_fusion(new).parameters == {"rank_constant": 0}
    with pytest.raises(ValueError):
        Settings(_env_file=None, chunk_size=20, chunk_overlap=20)
    with pytest.raises(ValueError, match="Unknown"):
        build_chunker(Settings(_env_file=None, chunker_mode="missing"))
    with pytest.raises(ValueError, match="Unknown"):
        build_fusion(Settings(_env_file=None, fusion_mode="missing"))
    chunks = build_chunker(Settings(_env_file=None, chunk_size=10, chunk_overlap=0))
    assert len(chunks.split(Document(content="abcdefghij" * 3))) == 3


@pytest.mark.parametrize("strategy", ["vector", "keyword", "hybrid"])
async def test_disabled_planner_ignores_llm_and_preserves_filters(strategy):
    runtime = build_query_planner(Settings(
        _env_file=None, query_planner_mode="disabled", default_retrieval_strategy=strategy,
        default_retrieval_rerank=False, default_top_k=3,
    ), structured_llm=object())
    plan = await runtime.planner.plan(Query(text="rewrite this?", filters={"tag": "x"}))
    assert plan.planner == "disabled"
    assert plan.strategy.value == strategy
    assert plan.filters == {"tag": "x"}
    assert plan.top_k == 3 and not plan.rerank and not plan.rewrite_required


async def test_custom_algorithms_in_service_and_ingestion(tmp_path, monkeypatch):
    from rag_framework.providers import algorithm_factory

    class WholeDocument(Chunker):
        def split(self, document):
            return [Chunk(id=document.id, document_id=document.id, index=0,
                          content=document.content)]

    class KeywordOnly(Fusion):
        def fuse(self, result_sets, *, top_k):
            return result_sets["keyword"][:top_k]

    chunks = AlgorithmRegistry(Chunker)
    fusion = AlgorithmRegistry(Fusion)
    chunks.register("whole", lambda _: WholeDocument())
    fusion.register("keyword_only", lambda _: KeywordOnly())
    with pytest.raises(ValueError, match="duplicate"):
        chunks.register("whole", lambda _: WholeDocument())
    monkeypatch.setattr(algorithm_factory, "chunkers", chunks)
    monkeypatch.setattr(algorithm_factory, "fusions", fusion)
    config = Settings(
        _env_file=None, query_planner_mode="disabled", answer_generator_mode="extractive",
        evaluation_judge_mode="heuristic", reranker_mode="disabled", keyword_backend="memory",
        chunker_mode="whole", fusion_mode="keyword_only",
        chroma_directory=tmp_path / "chroma", source_directory=tmp_path / "sources",
        knowledge_base_directory=tmp_path / "bases",
        evaluation_report_directory=tmp_path / "reports",
        evaluation_dataset_directory=tmp_path / "datasets",
    )
    service = build_service(config)
    try:
        runtime = service.knowledge_bases.runtime("default")
        source = runtime.sources.upload(b"alpha beta", "test.txt", "text")
        run = await runtime.sources.ingest(source["id"], AdapterOptions())
        assert run["status"] == "complete"
        assert run["chunker_parameters"] == {} and run["chunk_size"] is None
        trace = await runtime.retriever.retrieve(Query(text="alpha"))
        assert len(trace.final_context) == 1
        step = next(step for step in trace.steps if step.name == "fusion")
        assert step.details["implementation"] == "KeywordOnly"
        assert trace.steps[0].details["skipped"]
    finally:
        await service.close()
