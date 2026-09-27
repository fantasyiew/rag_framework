"""Configuration-driven provider construction."""

import logging

from rag_framework.config import Settings
from rag_framework.contracts.providers import KeywordStore
from rag_framework.providers.bm25 import InMemoryBM25KeywordStore
from rag_framework.providers.elasticsearch import ElasticsearchKeywordStore
from rag_framework.providers.resilient import ResilientKeywordStore

logger = logging.getLogger(__name__)


def create_keyword_store(config: Settings, *, index_name: str | None = None) -> KeywordStore:
    memory_store = InMemoryBM25KeywordStore()
    if config.keyword_backend == "memory":
        return memory_store

    try:
        primary = ElasticsearchKeywordStore(
            url=config.elasticsearch_url,
            index_name=index_name or config.elasticsearch_index,
            analyzer=config.elasticsearch_analyzer,
            bm25_k1=config.elasticsearch_bm25_k1,
            bm25_b=config.elasticsearch_bm25_b,
            api_key=(
                config.elasticsearch_api_key.get_secret_value()
                if config.elasticsearch_api_key is not None
                else None
            ),
            username=config.elasticsearch_username,
            password=(
                config.elasticsearch_password.get_secret_value()
                if config.elasticsearch_password is not None
                else None
            ),
            verify_certs=config.elasticsearch_verify_certs,
            request_timeout=config.elasticsearch_request_timeout,
        )
    except RuntimeError:
        logger.exception("Elasticsearch client is unavailable; using in-memory BM25")
        return memory_store
    return ResilientKeywordStore(primary, memory_store)
