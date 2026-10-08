"""Shared service composition for HTTP and Python consumers."""
import hashlib
from dataclasses import dataclass, field
from typing import Any

from rag_framework.config import Settings
from rag_framework.contracts.lifecycle import AsyncClosable, ChunkSnapshot
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
from rag_framework.knowledge_bases.bindings import (
    BindingStore,
    bound_embedder,
    embedding_profile,
    profile_settings,
)
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.pipeline.managed import ManagedIndexingPipeline, ManagedRetriever
from rag_framework.presets import config_snapshot
from rag_framework.providers import (
    build_answer_generator,
    build_answer_judge,
    build_query_planner,
    build_reranker,
    create_keyword_store,
)
from rag_framework.providers.algorithm_factory import build_chunker, build_fusion
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

    def audit_snapshot(self, knowledge_base_id: str | None = None):
        snapshot = config_snapshot(self.settings)
        from rag_framework.hot_config import read_state
        snapshot['config_version'] = read_state(self.settings.managed_config_path)['version']
        snapshot["components"] = {
            name: {"configured": info.configured, "active": info.active,
                   "implementation": info.implementation}
            for name, info in self.components.items()
        }
        if knowledge_base_id is not None:
            snapshot['knowledge_base_id'] = knowledge_base_id
            snapshot['embedding_binding'] = self.knowledge_bases.bindings.get(knowledge_base_id)
        return snapshot

    def retrieval_evaluator(self, knowledge_base_id: str = "default"):
        return RetrievalEvaluator(
            self.knowledge_bases.runtime(knowledge_base_id).retriever,
            self.evaluation_store, concurrency=self.settings.evaluation_concurrency,
            config_snapshot=self.audit_snapshot(knowledge_base_id),
            metrics=self.settings.evaluation_metrics,
        )

    def rag_evaluator(self, knowledge_base_id: str = "default"):
        return RAGEvaluator(
            self.knowledge_bases.runtime(knowledge_base_id).generation_pipeline,
            self.evaluation_store, concurrency=self.settings.evaluation_concurrency,
            judge=self.judge_runtime.judge,
            metrics=self.settings.evaluation_metrics,
            config_snapshot=self.audit_snapshot(knowledge_base_id),
        )

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            await self.knowledge_bases.close()
        finally:
            if isinstance(self.reranker, AsyncClosable):
                await self.reranker.close()


def build_service(settings: Settings) -> ServiceRuntime:
    from rag_framework.evaluation.registry import select_metrics
    select_metrics(settings.evaluation_metrics)
    bindings = BindingStore(settings.knowledge_base_directory)
    default_profile = bindings.get('default')
    embedding = bound_embedder(profile_settings(settings, default_profile) if default_profile else settings, default_profile)
    embedder = embedding.embedder
    planner_runtime = build_query_planner(settings)
    generator_runtime = build_answer_generator(settings)
    judge_runtime = build_answer_judge(settings)
    reranker = build_reranker(settings)

    def runtime_factory(knowledge_base_id: str) -> KnowledgeBaseRuntime:
        profile = bindings.get(knowledge_base_id)
        runtime_settings = profile_settings(settings, profile) if profile else settings
        runtime_embedding = embedding if knowledge_base_id == 'default' and not hasattr(runtime_factory, 'default_built') else bound_embedder(runtime_settings, profile)
        if knowledge_base_id == 'default':
            runtime_factory.default_built = True
        runtime_embedder = runtime_embedding.embedder
        suffix = "" if knowledge_base_id == "default" else f"_{knowledge_base_id}"
        base_collection = settings.qdrant_collection if settings.vector_backend == 'qdrant' else settings.chroma_collection
        vector_directory = settings.qdrant_directory if settings.vector_backend == 'qdrant' else settings.chroma_directory
        collection = f"{base_collection}{suffix}"
        index_name = f"{settings.elasticsearch_index}{suffix}"
        runtime_vector_store = build_vector_store(runtime_settings, collection_name=collection)
        runtime_keyword_store = create_keyword_store(settings, index_name=index_name)
        chunker = build_chunker(settings)
        source_directory = (settings.source_directory if knowledge_base_id == "default" else
                            settings.knowledge_base_directory / knowledge_base_id / "sources")
        state = IndexState(source_directory, {
            "embedding": runtime_embedding.fingerprint,
            "chunker": {"implementation": type(chunker).__module__ + "." + type(chunker).__qualname__,
                        "parameters": chunker.parameters},
            "vector": {"backend": settings.vector_backend,
                       "implementation": type(runtime_vector_store).__module__ + "." + type(runtime_vector_store).__qualname__,
                       "collection": collection,
                       "directory": str(vector_directory.resolve())},
            "keyword": {"backend": settings.keyword_backend,
                        "implementation": type(runtime_keyword_store).__name__, "index": index_name,
                        "endpoint_digest": hashlib.sha256(settings.elasticsearch_url.encode()).hexdigest()},
        }, runtime_vector_store, runtime_keyword_store)
        from rag_framework.providers.bm25 import InMemoryBM25KeywordStore
        memory_index = getattr(runtime_keyword_store, 'fallback', runtime_keyword_store)
        manifest = state.manifest()
        if runtime_embedding.active_mode == 'unavailable':
            state.model_blocked = '绑定的嵌入模型不可用，请检查配置和密钥环境变量'
        state.on_complete = lambda: bindings.save(knowledge_base_id,
            bindings.get(knowledge_base_id) or embedding_profile(runtime_settings, runtime_embedding.active_mode))
        if profile is None:
            if manifest and manifest.get('fingerprint', {}).get('embedding') == runtime_embedding.fingerprint:
                bindings.save(knowledge_base_id, embedding_profile(runtime_settings, runtime_embedding.active_mode))
            elif manifest or state.documents():
                state.binding_required = True
        if (isinstance(memory_index, InMemoryBM25KeywordStore)
                and isinstance(runtime_vector_store, ChunkSnapshot)
                and manifest and manifest.get('state') == 'ready'
                and manifest.get('fingerprint') == state.fingerprint):
            # Restore only actual indexed chunks, never cleared or failed recovery archives.
            memory_index.restore_chunks(runtime_vector_store.snapshot_chunks())
        runtime_indexing = ManagedIndexingPipeline(
            chunker, runtime_embedder, runtime_vector_store, runtime_keyword_store, state=state
        )
        runtime_retriever = ManagedRetriever(
            runtime_vector_store,
            runtime_embedder,
            planner_runtime.planner,
            runtime_keyword_store,
            reranker=reranker,
            top_k_limit=settings.default_top_k,
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
        from rag_framework.hot_config import read_state
        runtime_retriever.config_identity = {
            'version': read_state(settings.managed_config_path)['version'],
            'config_hash': config_snapshot(settings)['config_hash'],
            'knowledge_base_id': knowledge_base_id,
            'embedding_fingerprint': runtime_embedding.fingerprint,
        }
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
            embedder=runtime_embedder,
        )
    
    default = runtime_factory("default")
    manager = KnowledgeBaseManager(settings.knowledge_base_directory, default, runtime_factory)
    manager.bindings = bindings
    manager.default_profile = lambda: embedding_profile(settings,
        ('compatible' if settings.embedding_api_key else 'hash') if settings.embedding_mode == 'auto'
        else settings.embedding_mode)
    manager.validate_profile = lambda profile: profile_settings(settings, profile)
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
    service = ServiceRuntime(
        settings, manager, planner_runtime, generator_runtime, judge_runtime, reranker,
        EvaluationStore(limit=settings.evaluation_report_limit,
                        directory=settings.evaluation_report_directory),
        EvaluationDatasetStore(settings.evaluation_dataset_directory,
                               max_cases=settings.evaluation_dataset_max_cases),
        components, embedder=embedder,
    )

    def runtime_changed(key):
        if key == 'default':
            runtime = manager.runtime(key)
            service.embedder = runtime.embedder
            fingerprint = runtime.index_state.fingerprint['embedding']
            service.components['embedding'] = ComponentInfo(
                manager.bindings.get(key)['settings']['embedding_mode'],
                fingerprint.get('provider', 'unavailable'), type(runtime.embedder).__name__, fingerprint)

    manager.on_runtime_change = runtime_changed
    return service
