"""Read-only configuration metadata and isolated draft validation."""

import math

from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from rag_framework.config import Settings
from rag_framework.presets import SECRET_FIELDS, validate_preset


def configuration_schema():
    from rag_framework.providers.algorithm_factory import chunkers, fusions
    from rag_framework.providers.embedding_factory import embedders
    from rag_framework.providers.vector_factory import vector_stores
    schema = Settings.model_json_schema()
    fields = {}
    for name, specification in schema['properties'].items():
        if name in SECRET_FIELDS or name == 'service_preset':
            continue
        group = ('数据与索引' if name.startswith(('embedding_', 'chroma_', 'qdrant_', 'chunk', 'vector_', 'source_', 'knowledge_base_'))
                 else '融合与重排' if name.startswith(('fusion_', 'rrf_', 'reranker_'))
                 else '生成与评估' if name.startswith(('generation_', 'answer_', 'evaluation_'))
                 else '检索与规划')
        rebuild = name.startswith(('embedding_', 'chunk', 'vector_', 'chroma_', 'qdrant_'))
        fields[name] = {**specification, 'group': group, 'requires_rebuild_review': rebuild,
                       'activation': 'restart', 'env': 'RAG_' + name.upper()}
        fields[name]['default'] = to_jsonable_python(Settings.model_fields[name].get_default(call_default_factory=True))
    for name, registry in (('chunker_mode', chunkers), ('fusion_mode', fusions),
                           ('embedding_mode', embedders), ('vector_backend', vector_stores)):
        fields[name]['enum'] = list(registry.factories) + (['auto'] if name == 'embedding_mode' else [])
    return {'schema_version': 1, 'fields': fields}


def validate_draft(payload):
    try:
        preset = validate_preset(payload, Settings.model_fields)
        # Never consult the host environment or resolve secret references during validation.
        class DraftSettings(Settings):
            @classmethod
            def settings_customise_sources(cls, settings_cls, init_settings, env_settings,
                                           dotenv_settings, file_secret_settings):
                return (init_settings,)
        config = DraftSettings(_env_file=None, **preset.settings)
        from rag_framework.evaluation.registry import select_metrics
        select_metrics(config.evaluation_metrics)
        from rag_framework.providers.algorithm_factory import chunkers, fusions
        from rag_framework.providers.embedding_factory import embedders
        from rag_framework.providers.vector_factory import vector_stores
        for name, registry in (('chunker_mode', chunkers), ('fusion_mode', fusions),
                               ('embedding_mode', embedders), ('vector_backend', vector_stores)):
            value = getattr(config, name)
            if value not in registry.factories and not (name == 'embedding_mode' and value == 'auto'):
                return {'valid': False, 'errors': [{'field': name, 'message': '未知组件模式'}]}
        if any(value < 0 or not math.isfinite(value) for value in config.fusion_weights.values()):
            return {'valid': False, 'errors': [{'field': 'fusion_weights', 'message': '权重必须为非负有限数值'}]}
        return {'valid': True, 'errors': [], 'activation': 'restart'}
    except ValidationError as exc:
        return {'valid': False, 'errors': [{'field': '.'.join(map(str, error['loc'])),
                  'message': error['msg']} for error in exc.errors(include_input=False, include_context=False)]}
    except (ValueError, TypeError, AttributeError):
        return {'valid': False, 'errors': [{'field': 'preset', 'message': '配置字段、引用或指标名称无效'}]}
