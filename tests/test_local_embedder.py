import asyncio
import sys
from types import SimpleNamespace

import pytest

from rag_framework.config import Settings
from rag_framework.core.vectors import EmbeddingError
from rag_framework.providers.embedding_factory import build_embedder


def settings(**kwargs):
    return Settings(_env_file=None, embedding_mode='sentence_transformers',
                    embedding_model='cached-model', embedding_dimensions=2, **kwargs)


async def test_local_lazy_load_prefixes_and_parameters(monkeypatch):
    calls = []

    class Model:
        def __init__(self, name, **kwargs):
            calls.append((name, kwargs))

        def get_sentence_embedding_dimension(self):
            return 2

        def encode(self, texts, **kwargs):
            calls.append((texts, kwargs))
            return SimpleNamespace(tolist=lambda: [[1.0, 0.0] for _ in texts])

    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=Model))
    runtime = build_embedder(settings(embedding_query_prefix='q: ', embedding_document_prefix='d: '))
    assert calls == []
    assert await runtime.embedder.embed_documents([]) == []
    assert calls == []
    await asyncio.gather(runtime.embedder.embed_documents(['one']), runtime.embedder.embed_query('two'))
    assert len(calls) == 3
    assert calls[0][1]['local_files_only'] is True
    assert calls[0][1]['trust_remote_code'] is False
    assert {entry[0][0] for entry in calls[1:]} == {'d: one', 'q: two'}
    assert calls[1][1]['normalize_embeddings'] is True
    assert calls[1][1]['prompt'] == ''


@pytest.mark.parametrize('failure', ['load', 'dimension', 'vector'])
async def test_local_fail_closed_and_redacts_errors(monkeypatch, failure):
    class Model:
        def __init__(self, *args, **kwargs):
            if failure == 'load':
                raise RuntimeError('private-path-or-token')

        def get_sentence_embedding_dimension(self):
            return 3 if failure == 'dimension' else 2

        def encode(self, *args, **kwargs):
            return SimpleNamespace(tolist=lambda: [[float('nan'), 0.0]])

    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=Model))
    with pytest.raises(EmbeddingError, match='Local embedding failed') as caught:
        await build_embedder(settings()).embedder.embed_query('test')
    assert 'private' not in str(caught.value)


def test_local_fingerprint_captures_semantic_changes():
    original = build_embedder(settings()).fingerprint
    for changed in ({'embedding_normalize': False}, {'embedding_query_prefix': 'q:'},
                    {'embedding_document_prefix': 'd:'}, {'embedding_model_revision': 'v2'}):
        assert build_embedder(settings(**changed)).fingerprint != original
    assert build_embedder(settings(embedding_device='cuda')).fingerprint == original
    with pytest.raises(ValueError, match='embedding_model'):
        build_embedder(Settings(_env_file=None, embedding_mode='sentence_transformers'))
