"""Credential readiness without returning or logging credential values."""
import os
from dotenv import dotenv_values

FIELDS = {
    'embedding_api_key': ('embedding', '嵌入 API Key'),
    'planner_api_key': ('planner', '规划 API Key'),
    'generation_api_key': ('generation', '生成 API Key'),
    'evaluation_judge_api_key': ('judge', '评估 API Key'),
    'reranker_cloud_api_key': ('reranker', '云端重排 API Key'),
    'elasticsearch_api_key': ('keyword', 'Elasticsearch API Key'),
    'elasticsearch_username': ('keyword', 'Elasticsearch 用户名'),
    'elasticsearch_password': ('keyword', 'Elasticsearch 密码'),
}

def resolve_credential(base, field, reference=None):
    reference = reference or 'RAG_' + field.upper()
    if reference in os.environ:
        value = os.environ[reference]
    elif reference == 'RAG_' + field.upper():
        value = getattr(base, field, None)
    else:
        value = dotenv_values('.env').get(reference)
    if hasattr(value, 'get_secret_value'):
        value = value.get_secret_value()
    return value if value and value.strip() else None

def credential_readiness(config, base, references):
    keys = {name: resolve_credential(base, name, references.get(name)) for name in FIELDS}
    inherited = {'generation_api_key': ['planner_api_key'],
                 'evaluation_judge_api_key': ['generation_api_key', 'planner_api_key'],
                 'reranker_cloud_api_key': ['planner_api_key']}
    statuses = {}
    for name in FIELDS:
        source = name if keys[name] else next((item for item in inherited.get(name, []) if keys[item]), None)
        statuses[name] = {'reference': references.get(name) or 'RAG_' + name.upper(),
                          'configured': bool(source), 'inherited_from': source if source != name else None}
    errors, warnings = [], []
    def require(field, message):
        errors.append({'field': field, 'message': message})
    remote_embedding = config.embedding_mode in {'compatible', 'openai', 'dashscope'} or (config.embedding_mode == 'auto' and keys['embedding_api_key'])
    if remote_embedding:
        required = ('embedding_model', 'embedding_base_url') if config.embedding_mode in {'compatible', 'auto'} else ('embedding_model',)
        for field in required:
            if not getattr(config, field): require(field, '远程嵌入必须配置此项')
        if not keys['embedding_api_key']: require('embedding_api_key', '远程嵌入缺少密钥；请配置引用的环境变量或 .env 后重启服务')
    for mode_field, key_field in [('query_planner_mode', 'planner_api_key'), ('answer_generator_mode', 'generation_api_key'), ('evaluation_judge_mode', 'evaluation_judge_api_key')]:
        mode = getattr(config, mode_field)
        if mode == 'llm' and not statuses[key_field]['configured']:
            require(key_field, 'LLM 模式缺少密钥（含可继承的密钥），请在环境变量或 .env 配置后重启')
        elif mode == 'auto' and not statuses[key_field]['configured']:
            warnings.append(f'{mode_field} 未配置可用密钥，将使用非 LLM 降级模式')
    if config.embedding_mode == 'auto' and not keys['embedding_api_key']:
        warnings.append('embedding_mode=auto 无密钥，将使用 hash，而非远程模型')
    if config.reranker_mode == 'cloud':
        if not statuses['reranker_cloud_api_key']['configured']: require('reranker_cloud_api_key', '云端重排缺少密钥（可继承规划密钥）')
        if not config.reranker_cloud_url: require('reranker_cloud_url', '云端重排必须配置端点')
    if config.keyword_backend == 'elasticsearch' and not keys['elasticsearch_api_key']:
        if bool(keys['elasticsearch_username']) != bool(keys['elasticsearch_password']):
            require('elasticsearch_password', 'Elasticsearch 用户名和密码必须同时配置；也可使用 API Key 或匿名连接')
    return {'credentials': statuses, 'errors': errors, 'warnings': warnings}
