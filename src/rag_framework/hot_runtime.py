"""Prepare replacement pipelines while retaining indexed storage and source archives."""

from dataclasses import replace

from rag_framework.hot_config import read_state
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.pipeline.managed import ManagedRetriever
from rag_framework.presets import config_snapshot
from rag_framework.providers import build_answer_generator, build_answer_judge, build_query_planner
from rag_framework.providers.algorithm_factory import build_fusion
from rag_framework.service import ComponentInfo


def prepare_update(service, config):
    planner = build_query_planner(config)
    generator = build_answer_generator(config)
    judge = build_answer_judge(config)
    fusion = build_fusion(config)
    version = read_state(config.managed_config_path)['version'] + 1
    fingerprint = config_snapshot(config)['config_hash']

    def rebuild(runtime):
        retriever = ManagedRetriever(runtime.vector_store, service.embedder, planner.planner,
            runtime.keyword_store, reranker=service.reranker,
            reranker_candidate_k=config.reranker_candidate_k,
            reranker_fail_open=config.reranker_mode == 'auto',
            hybrid_candidate_multiplier=config.hybrid_candidate_multiplier,
            fusion=fusion, state=runtime.index_state)
        retriever.config_identity = {'version': version, 'config_hash': fingerprint}
        return replace(runtime, retriever=retriever, generation_pipeline=GenerationPipeline(
            retriever, generator.generator, max_context_chunks=config.generation_max_context_chunks))

    replacements = {key: rebuild(runtime) for key, runtime in service.knowledge_bases._runtimes.items()}
    components = dict(service.components)
    components['fusion'] = ComponentInfo(config.fusion_mode, config.fusion_mode,
                                        type(fusion).__name__, fusion.parameters)
    for name, runtime, component in [('planner', planner, planner.planner),
                                    ('generator', generator, generator.generator),
                                    ('judge', judge, judge.judge)]:
        components[name] = ComponentInfo(runtime.configured_mode, runtime.active_mode,
            type(component).__name__, fallback_reason=runtime.fallback_reason)

    def commit():
        manager = service.knowledge_bases
        base_factory = getattr(manager, '_base_runtime_factory', manager._runtime_factory)
        manager._base_runtime_factory = base_factory
        manager._runtime_factory = lambda key: rebuild(base_factory(key))
        manager._runtimes = replacements
        # The original factory closes over this Settings instance; hot fields never affect indexing.
        service.settings.__dict__.update(config.__dict__)
        service.planner_runtime, service.generator_runtime, service.judge_runtime = planner, generator, judge
        service.components = components
    return commit
