from rag_framework.core.models import Document
from rag_framework.pipeline.indexing import CharacterChunker


def test_chunker_preserves_document_identity() -> None:
    document = Document(id="doc-1", content="a" * 20)
    chunks = CharacterChunker(chunk_size=10, overlap=2).split(document)

    assert [chunk.document_id for chunk in chunks] == ["doc-1", "doc-1", "doc-1"]
    assert chunks[1].content.startswith("a" * 10)
