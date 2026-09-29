import pytest

pytest.importorskip('qdrant_client')

from rag_framework.config import Settings
from rag_framework.core.models import Chunk
from rag_framework.core.vectors import EmbeddingError
from rag_framework.providers.vector_factory import build_vector_store


async def test_qdrant_contract_persistence_isolation_filters_and_clear(tmp_path):
    config = Settings(_env_file=None, vector_backend='qdrant',
                      qdrant_directory=tmp_path, embedding_dimensions=2)
    store = build_vector_store(config)
    other = build_vector_store(config, collection_name='other')
    chunk = Chunk(id='arbitrary:chunk/1', document_id='doc', index=0, content='hello',
                  metadata={'city': 'Tokyo', 'nested': {'x': 1}})
    try:
        assert await store.search([1.0, 0.0], top_k=2, filters={}) == []
        await store.upsert([chunk], [[1.0, 0.0]])
        await store.upsert([chunk], [[1.0, 0.0]])
        assert await store.count() == 1
        assert await other.count() == 0
        hits = await store.search([1.0, 0.0], top_k=2, filters={'city': 'Tokyo'})
        assert hits[0].chunk == chunk
        assert hits[0].score == pytest.approx(1.0)
        assert await store.search([1.0, 0.0], top_k=2, filters={'city': 'Paris'}) == []
        with pytest.raises(ValueError):
            await store.search([1.0, 0.0], top_k=2, filters={'city': {'$in': ['Tokyo']}})
        with pytest.raises(EmbeddingError):
            await store.upsert([chunk], [[1.0]])
        assert await store.health()
    finally:
        await store.close()
        await other.close()
    reopened = build_vector_store(config)
    try:
        assert await reopened.count() == 1
        assert await reopened.clear() == 1
        assert await reopened.count() == 0
        await reopened.upsert([chunk], [[0.0, 1.0]])
        assert await reopened.count() == 1
    finally:
        await reopened.close()
        await reopened.close()
