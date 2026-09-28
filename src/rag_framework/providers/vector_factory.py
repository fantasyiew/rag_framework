"""Vector backend registry; framework supplies precomputed vectors."""

from rag_framework.config import Settings
from rag_framework.contracts.lifecycle import AsyncClosable, HealthCheck, IndexAdmin
from rag_framework.contracts.providers import VectorStore
from rag_framework.providers.algorithm_factory import AlgorithmRegistry
from rag_framework.providers.chroma import ChromaVectorStore

vector_stores = AlgorithmRegistry(VectorStore)
vector_stores.register("chroma", lambda s: ChromaVectorStore(s.chroma_directory, s.chroma_collection))


def build_vector_store(settings: Settings, *, collection_name: str | None = None) -> VectorStore:
    config = settings.model_copy(update={"chroma_collection": collection_name or settings.chroma_collection})
    store = vector_stores.build(config.vector_backend, config)
    if not all(isinstance(store, capability) for capability in (IndexAdmin, HealthCheck, AsyncClosable)):
        raise TypeError("Managed vector stores require IndexAdmin, HealthCheck and AsyncClosable")
    return store
