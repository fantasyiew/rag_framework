import pytest

from rag_framework.core.models import Document
from rag_framework.providers.hash_embedder import HashEmbedder
from rag_framework.providers.langchain import LangChainDocumentAdapter


def test_document_adapter_round_trips_framework_fields() -> None:
    original = Document(id="doc-1", content="A framework document", source_uri="memory://doc", metadata={"team": "ai"})

    restored = LangChainDocumentAdapter.to_core(LangChainDocumentAdapter.to_langchain(original))

    assert restored.id == original.id
    assert restored.content == original.content
    assert restored.source_uri == original.source_uri
    assert restored.metadata == original.metadata


@pytest.mark.asyncio
async def test_hash_embedder_uses_langchain_embeddings_contract() -> None:
    embedder = HashEmbedder(dimensions=16)

    assert len(await embedder.embed_query("retrieval trace")) == 16
