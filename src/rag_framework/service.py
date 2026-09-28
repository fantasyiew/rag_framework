"""Shared service composition for HTTP and Python consumers."""
import hashlib
from dataclasses import dataclass, field
from typing import Any

from rag_framework.config import Settings
from rag_framework.contracts.lifecycle import AsyncClosable
from rag_framework.evaluation import (
    EvaluationDatasetStore,
    EvaluationStore,
    RAGEvaluator,
    RetrievalEvaluator,
)
from rag_framework.index_state import IndexState
from rag_framework.knowledge_bases import (
    KnowledgeBaseManager,
    KnowledgeBaseRuntime,
)
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.pipeline.managed import ManagedIndexingPipeline, ManagedRetriever
from rag_framework.providers import (
    build_answer_generator,
    build_answer_judge,
    build_query_planner,
    build_reranker,
    create_keyword_store,
)
from rag_framework.providers.algorithm_factory import build_chunker, build_fusion
from rag_framework.providers.embedding_factory import build_embedder
from rag_framework.providers.vector_factory import build_vector_store
from rag_framework.sources.service import SourceService


@dataclass(frozen=True)
class ComponentInfo:
    configured: str
    active: str
    implementation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    fallback_reason: str | None = None


@dataclass
class ServiceRuntime:
    settings: Settings
    knowledge_bases: KnowledgeBaseManager
    planner_runtime: Any
    generator_runtime: Any
    judge_runtime: Any
    reranker: Any
    evaluation_store: EvaluationStore
    evaluation_dataset_store: EvaluationDatasetStore
    components: dict[str, ComponentInfo]
    embedder: Any = None
    _closed: bool = False

    def retrieval_evaluator(self, knowledge_base_id: str = "default"):
        return RetrievalEvaluator(
            self.knowledge_bases.runtime(knowledge_base_id).retriever,
            self.evaluation_store, concurrency=self.settings.evaluation_concurrency,
        )

    def rag_evaluator(self, knowledge_base_id: str = "default"):
        return RAGEvaluator(
            self.knowledge_bases.runtime(knowledge_base_id).generation_pipeline,
            self.evaluation_store, concurrency=self.settings.evaluation_concurrency,
            judge=self.judge_runtime.judge,
        )

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            await self.knowledge_bases.close()
        finally:
            try:
                if isinstance(self.reranker, AsyncClosable):
                    await self.reranker.close()
            finally:
                if isinstance(self.embedder, AsyncClosable):
                    await self.embedder.close()


def build_service(settings: Settings) -> ServiceRuntime:
    embedding = build_embedder(settings)
    embedder = embedding.embedder
    planner_runtime = build_query_planner(settings)
    generator_runtime = build_answer_generator(settings)
    judge_runtime = build_answer_judge(settings)
    reranker = build_reranker(settings)

    def runtime_factory(knowledge_base_id: str) -> KnowledgeBaseRuntime:
        suffix = "" if knowledge_base_id == "default" else f"_{knowledge_base_id}"
        collection = f"{settings.chroma_collection}{suffix}"
        index_name = f"{settings.elasticsearch_index}{suffix}"
        runtime_vector_store = build_vector_store(settings, collection_name=collection)
        runtime_keyword_store = create_keyword_store(settings, index_name=index_name)
        chunker = build_chunker(settings)
        source_directory = (settings.source_directory if knowledge_base_id == "default" else
                            settings.knowledge_base_directory / knowledge_base_id / "sources")
        state = IndexState(source_directory, {
            "embedding": embedding.fingerprint,
            "chunker": {"implementation": type(chunker).__module__ + "." + type(chunker).__qualname__,
                        "parameters": chunker.parameters},
            "vector": {"backend": settings.vector_backend,
                       "implementation": type(runtime_vector_store).__module__ + "." + type(runtime_vector_store).__qualname__,
                       "collection": collection,
                       "directory": str(settings.chroma_directory.resolve())},
            "keyword": {"backend": settings.keyword_backend,
                        "implementation": type(runtime_keyword_store).__name__, "index": index_name,
                        "endpoint_digest": hashlib.sha256(settings.elasticsearch_url.encode()).hexdigest()},
        }, runtime_vector_store, runtime_keyword_store)
        runtime_indexing = ManagedIndexingPipeline(
            chunker, embedder, runtime_vector_store, runtime_keyword_store, state=state
        )
        runtime_retriever = ManagedRetriever(
            runtime_vector_store,
            embedder,
            planner_runtime.planner,
            runtime_keyword_store,
            reranker=reranker,
            reranker_candidate_k=settings.reranker_candidate_k,
            reranker_fail_open=settings.reranker_mode == "auto",
            hybrid_candidate_multiplier=settings.hybrid_candidate_multiplier,
            rrf_rank_constant=settings.effective_fusion_rank_constant,
            fusion=build_fusion(settings),
            state=state,
        )
        runtime_generation = GenerationPipeline(
            runtime_retriever,
            generator_runtime.generator,
            max_context_chunks=settings.generation_max_context_chunks,
        )
        runtime_sources = SourceService(
            source_directory, runtime_indexing
        )
        return KnowledgeBaseRuntime(
            vector_store=runtime_vector_store,
            keyword_store=runtime_keyword_store,
            indexing_pipeline=runtime_indexing,
            retriever=runtime_retriever,
            generation_pipeline=runtime_generation,
            sources=runtime_sources,
            index_state=state,
        )
    
    default = runtime_factory("default")
    manager = KnowledgeBaseManager(settings.knowledge_base_directory, default, runtime_factory)
    components = {
        "embedding": ComponentInfo(embedding.configured_mode, embedding.active_mode,
                                   type(embedder).__name__, embedding.fingerprint,
                                   embedding.fallback_reason),
        "vector_store": ComponentInfo(settings.vector_backend, settings.vector_backend,
                                      type(default.vector_store).__name__),
        "chunker": ComponentInfo(settings.chunker_mode, settings.chunker_mode,
            type(default.indexing_pipeline.chunker).__name__,
            default.indexing_pipeline.chunker.parameters),
        "fusion": ComponentInfo(settings.fusion_mode, settings.fusion_mode,
            type(default.retriever.fusion).__name__, default.retriever.fusion.parameters,
            fallback_reason=("New fusion rank constant overrides legacy RRF rank constant"
                if settings.fusion_rank_constant is not None
                and "rrf_rank_constant" in settings.model_fields_set
                and settings.fusion_rank_constant != settings.rrf_rank_constant else None)),
        "keyword_store": ComponentInfo(settings.keyword_backend,
            "elasticsearch" if hasattr(default.keyword_store, "primary") else "memory",
            type(default.keyword_store).__name__,
            fallback_reason=("Elasticsearch initialization unavailable" if
                settings.keyword_backend == "elasticsearch" and
                not hasattr(default.keyword_store, "primary") else None)),
        "reranker": ComponentInfo(settings.reranker_mode,
            "disabled" if reranker is None else
            ("cloud" if type(reranker).__name__ == "CloudReranker" else "cross_encoder"),
            type(reranker).__name__),
    }
    for name, runtime, component in [
        ("planner", planner_runtime, planner_runtime.planner),
        ("generator", generator_runtime, generator_runtime.generator),
        ("judge", judge_runtime, judge_runtime.judge),
    ]:
        components[name] = ComponentInfo(
            runtime.configured_mode, runtime.active_mode, type(component).__name__,
            fallback_reason=runtime.fallback_reason,
        )
    return ServiceRuntime(
        settings, manager, planner_runtime, generator_runtime, judge_runtime, reranker,
        EvaluationStore(limit=settings.evaluation_report_limit,
                        directory=settings.evaluation_report_directory),
        EvaluationDatasetStore(settings.evaluation_dataset_directory,
                               max_cases=settings.evaluation_dataset_max_cases),
        components, embedder=embedder,
    )
