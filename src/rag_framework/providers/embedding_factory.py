"""Embedding factories with stable identity and no runtime model fallback."""

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from rag_framework.config import Settings
from rag_framework.contracts.providers import Embedder
from rag_framework.core.vectors import EmbeddingError, validate_vectors
from rag_framework.providers.algorithm_factory import AlgorithmRegistry
from rag_framework.providers.hash_embedder import HashEmbedder
from rag_framework.providers.local_embedder import SentenceTransformerEmbedder
from rag_framework.providers.sdk_embeddings import OpenAIEmbedder, DashScopeEmbedder


class CompatibleEmbedder(Embedder):
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None):
        if not settings.embedding_model or not settings.embedding_base_url or not settings.embedding_api_key:
            missing = [name for name in ('embedding_model', 'embedding_base_url', 'embedding_api_key') if not getattr(settings, name)]
            raise ValueError('远程嵌入缺少配置：' + '、'.join(missing) + '。密钥请通过服务端环境变量或 .env 配置，并检查知识库密钥引用。')
        parsed = urlsplit(settings.embedding_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("Embedding base URL must be HTTP(S), without credentials/query/fragment")
        self.config = settings
        self.url = settings.embedding_base_url.rstrip("/") + "/embeddings"
        self.client = client or httpx.AsyncClient(timeout=settings.embedding_request_timeout)
        self.owns_client = client is None

    async def embed_documents(self, texts):
        output = []
        for start in range(0, len(texts), self.config.embedding_batch_size):
            batch = texts[start:start + self.config.embedding_batch_size]
            payload = {"model": self.config.embedding_model, "input": batch,
                       "encoding_format": "float"}
            if self.config.embedding_send_dimensions:
                payload["dimensions"] = self.config.embedding_dimensions
            try:
                response = await self.client.post(
                    self.url, json=payload,
                    headers={"Authorization": "Bearer " + self.config.embedding_api_key.get_secret_value()},
                )
                response.raise_for_status()
                items = response.json()["data"]
                if len(items) != len(batch) or sorted(item["index"] for item in items) != list(range(len(batch))):
                    raise ValueError("Invalid embedding indices")
                vectors = [item["embedding"] for item in sorted(items, key=lambda item: item["index"])]
                output.extend(validate_vectors(vectors, len(batch), self.config.embedding_dimensions))
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                # Do not include provider bodies, URLs, prompts or credentials in public errors.
                raise EmbeddingError("Remote embedding request or response validation failed") from None
        return output

    async def embed_query(self, text):
        return (await self.embed_documents([text]))[0]

    async def close(self):
        if self.owns_client:
            await self.client.aclose()


@dataclass
class EmbeddingRuntime:
    embedder: Embedder
    fingerprint: dict
    configured_mode: str
    active_mode: str
    fallback_reason: str | None = None


embedders = AlgorithmRegistry(Embedder)
embedders.register("hash", lambda s: HashEmbedder(s.embedding_dimensions))
embedders.register("compatible", CompatibleEmbedder)
embedders.register("sentence_transformers", SentenceTransformerEmbedder)
embedders.register('openai', OpenAIEmbedder)
embedders.register('dashscope', DashScopeEmbedder)


def build_embedder(settings: Settings) -> EmbeddingRuntime:
    mode = settings.embedding_mode
    if mode == "auto":
        mode = "compatible" if settings.embedding_api_key else "hash"
    embedder = embedders.build(mode, settings)
    fingerprint = {
        "provider": mode, "implementation": type(embedder).__module__ + "." + type(embedder).__qualname__,
        "model": "hash-sha256-v1" if mode == "hash" else settings.embedding_model,
        "revision": settings.embedding_model_revision,
        "dimensions": settings.embedding_dimensions,
        "endpoint_digest": hashlib.sha256(getattr(embedder, 'endpoint', settings.embedding_base_url or '').rstrip('/').encode()).hexdigest()
            if mode != "hash" else None,
    }
    if mode == "sentence_transformers":
        fingerprint.update(
            endpoint_digest=None,
            normalize=settings.embedding_normalize,
            query_prefix=settings.embedding_query_prefix,
            document_prefix=settings.embedding_document_prefix,
            encoding="encode-float32-v1",
        )
    return EmbeddingRuntime(embedder, fingerprint, settings.embedding_mode, mode,
                            "No embedding credentials; selected hash" if
                            settings.embedding_mode == "auto" and mode == "hash" else None)
