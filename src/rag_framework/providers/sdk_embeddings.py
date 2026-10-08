"""SDK adapters; credentials and endpoints belong to individual instances."""
import asyncio
from urllib.parse import urlsplit

import httpx

from rag_framework.contracts.providers import Embedder
from rag_framework.core.vectors import EmbeddingError, validate_vectors

DEFAULT_ENDPOINTS = {
    'openai': 'https://api.openai.com/v1',
    'dashscope': 'https://dashscope.aliyuncs.com/api/v1',
}


def check_settings(config, mode):
    for name in ('embedding_model', 'embedding_api_key'):
        if not getattr(config, name):
            raise ValueError(f'{mode} 嵌入缺少配置：{name}')
    endpoint = (config.embedding_base_url or DEFAULT_ENDPOINTS[mode]).rstrip('/')
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('embedding_base_url 必须为无认证信息、查询参数及片段的 HTTP(S) 地址')
    return endpoint


class OpenAIEmbedder(Embedder):
    def __init__(self, config):
        self.endpoint = check_settings(config, 'openai')
        self.config = config
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError:
            raise ValueError('openai 嵌入需安装 rag-framework[openai-embedding]') from None
        self.sync_client = httpx.Client(timeout=config.embedding_request_timeout)
        self.async_client = httpx.AsyncClient(timeout=config.embedding_request_timeout)
        options = {'model': config.embedding_model, 'api_key': config.embedding_api_key,
                   'base_url': self.endpoint, 'chunk_size': config.embedding_batch_size,
                   'request_timeout': config.embedding_request_timeout, 'max_retries': 0,
                   'check_embedding_ctx_length': False,
                   'http_client': self.sync_client, 'http_async_client': self.async_client}
        if config.embedding_send_dimensions:
            options['dimensions'] = config.embedding_dimensions
        try:
            self.component = OpenAIEmbeddings(**options)
        except Exception:  # noqa: BLE001 - Provider errors can contain credentials.
            self.sync_client.close()
            # Construction occurs outside an awaitable scope; AsyncClient has not opened connections.
            raise ValueError('OpenAI 嵌入组件初始化失败，请检查配置及依赖版本') from None

    async def embed_documents(self, texts):
        if not texts:
            return []
        try:
            vectors = await self.component.aembed_documents(texts)
            return validate_vectors(vectors, len(texts), self.config.embedding_dimensions)
        except Exception:  # noqa: BLE001 - Never expose provider response bodies.
            raise EmbeddingError('OpenAI embedding request or response validation failed') from None

    async def embed_query(self, text):
        return (await self.embed_documents([text]))[0]

    async def close(self):
        self.sync_client.close()
        await self.async_client.aclose()


class DashScopeClient:
    """LangChain's client seam supplies per-call settings, never SDK globals."""
    def __init__(self, config, endpoint, sdk):
        self.config, self.endpoint, self.sdk = config, endpoint, sdk

    def call(self, **kwargs):
        kwargs.update(api_key=self.config.embedding_api_key.get_secret_value(),
                      base_address=self.endpoint,
                      request_timeout=self.config.embedding_request_timeout)
        if self.config.embedding_send_dimensions:
            kwargs['dimension'] = self.config.embedding_dimensions
        response = self.sdk.call(**kwargs)
        if response.status_code != 200:
            # Prevent LangChain retry logging from including provider response bodies.
            raise EmbeddingError('DashScope embedding request failed')
        items = response.output['embeddings']
        count = len(kwargs['input']) if isinstance(kwargs['input'], list) else 1
        if sorted(item['text_index'] for item in items) != list(range(count)):
            raise EmbeddingError('DashScope embedding response indices are invalid')
        response.output['embeddings'] = sorted(items, key=lambda item: item['text_index'])
        return response


class DashScopeEmbedder(Embedder):
    def __init__(self, config):
        self.endpoint = check_settings(config, 'dashscope')
        self.config = config
        try:
            from dashscope import TextEmbedding
            from langchain_community.embeddings import DashScopeEmbeddings
        except ImportError:
            raise ValueError('dashscope 嵌入需安装 rag-framework[dashscope-embedding]') from None
        # The upstream constructor writes dashscope.api_key globally. Use its declared
        # client seam with already-validated internal values to avoid cross-KB leakage.
        self.component = DashScopeEmbeddings.model_construct(
            model=config.embedding_model,
            dashscope_api_key=config.embedding_api_key.get_secret_value(),
            max_retries=1, client=DashScopeClient(config, self.endpoint, TextEmbedding))

    async def embed_documents(self, texts):
        vectors = []
        try:
            for start in range(0, len(texts), self.config.embedding_batch_size):
                batch = texts[start:start + self.config.embedding_batch_size]
                output = await asyncio.to_thread(self.component.embed_documents, batch)
                vectors.extend(validate_vectors(output, len(batch), self.config.embedding_dimensions))
            return vectors
        except Exception:  # noqa: BLE001 - Never expose provider response bodies.
            raise EmbeddingError('DashScope embedding request or response validation failed') from None

    async def embed_query(self, text):
        try:
            vector = await asyncio.to_thread(self.component.embed_query, text)
            return validate_vectors([vector], 1, self.config.embedding_dimensions)[0]
        except Exception:  # noqa: BLE001 - Never expose provider response bodies.
            raise EmbeddingError('DashScope embedding request or response validation failed') from None

    async def close(self):
        pass
