import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from rag_framework.config import Settings
from rag_framework.core.models import Document, Query
from rag_framework.core.vectors import EmbeddingError
from rag_framework.index_state import IndexCompatibilityError
from rag_framework.providers.embedding_factory import CompatibleEmbedder, build_embedder
from rag_framework.providers.vector_factory import build_vector_store
from rag_framework.service import build_service
from rag_framework.sources.adapters import AdapterOptions


def config(tmp_path, **options):
    values = {
        "query_planner_mode": "disabled", "default_retrieval_strategy": "vector",
        "answer_generator_mode": "extractive", "evaluation_judge_mode": "heuristic",
        "reranker_mode": "disabled", "keyword_backend": "memory", "embedding_dimensions": 16,
        "chroma_directory": tmp_path / "chroma", "source_directory": tmp_path / "sources",
        "knowledge_base_directory": tmp_path / "bases",
        "evaluation_report_directory": tmp_path / "reports",
        "evaluation_dataset_directory": tmp_path / "test_datasets",
    }
    return Settings(_env_file=None, **(values | options))


@pytest.mark.parametrize("changed", [
    {"embedding_dimensions": 32},
    {"embedding_model_revision": "different-same-dimension"},
    {"chunk_size": 400},
])
async def test_changed_fingerprint_blocks_query_and_write_until_rebuild(tmp_path, changed):
    first = build_service(config(tmp_path))
    base = first.knowledge_bases.runtime("default")
    await base.indexing_pipeline.index([Document(id="doc", content="alpha beta")])
    await first.close()
    second = build_service(config(tmp_path, **changed))
    base = second.knowledge_bases.runtime("default")
    if 'chunk_size' not in changed:
        # Global embedding defaults do not replace per-KB binding.
        assert (await base.index_state.describe())['status'] == 'ready'
        assert base.index_state.fingerprint['embedding']['dimensions'] == 16
        assert base.index_state.fingerprint['embedding']['revision'] is None
        assert len((await base.retriever.retrieve(Query(text='alpha'))).final_context) == 1
        await second.close()
        return
    assert (await base.index_state.describe())["status"] == "blocked"
    with pytest.raises(IndexCompatibilityError):
        await base.retriever.retrieve(Query(text="alpha"))
    with pytest.raises(IndexCompatibilityError):
        await base.indexing_pipeline.index([Document(content="blocked")])
    result = await base.sources.rebuild()
    assert result["status"] == "complete"
    assert len((await base.retriever.retrieve(Query(text="alpha"))).final_context) == 1
    assert base.index_state.manifest()["fingerprint"] == base.index_state.fingerprint
    await second.close()


async def test_rebuild_failure_preserves_inputs_and_retry_recovers(tmp_path):
    service = build_service(config(tmp_path))
    base = service.knowledge_bases.runtime("default")
    source = base.sources.upload(b"alpha beta", "file.txt", "text")
    await base.sources.ingest(source["id"], AdapterOptions())
    real_embed = base.indexing_pipeline.embedder.embed_documents
    base.indexing_pipeline.embedder.embed_documents = AsyncMock(side_effect=RuntimeError("secret"))
    failed = await base.sources.rebuild()
    assert failed["status"] == "failed" and "secret" not in str(failed)
    assert base.index_state.manifest()["state"] == "failed"
    assert len(base.sources.list_documents()) == 1
    with pytest.raises(IndexCompatibilityError):
        await base.retriever.retrieve(Query(text="alpha"))
    base.indexing_pipeline.embedder.embed_documents = real_embed
    assert (await base.sources.rebuild())["status"] == "complete"
    assert await base.vector_store.count() == 1
    await service.close()


async def test_legacy_nonempty_index_is_not_silently_adopted(tmp_path):
    service = build_service(config(tmp_path))
    base = service.knowledge_bases.runtime("default")
    document = Document(content="legacy")
    chunks = base.indexing_pipeline.chunker.split(document)
    await base.vector_store.upsert(chunks, await service.embedder.embed_documents(["legacy"]))
    assert base.index_state.manifest() is None
    with pytest.raises(IndexCompatibilityError, match="旧索引"):
        await base.retriever.retrieve(Query(text="legacy"))
    result = await base.sources.rebuild()
    assert result["status"] == "failed"
    assert await base.vector_store.count() == 1  # no recovery input: refuse to erase
    await service.close()


async def test_clear_then_rebuild_keeps_direct_document_archive(tmp_path):
    service = build_service(config(tmp_path))
    base = service.knowledge_bases.runtime("default")
    await base.indexing_pipeline.index([Document(content="direct input")])
    await base.sources.clear()
    assert await base.vector_store.count() == 0
    assert len(base.indexing_pipeline.canonical_documents()) == 1
    assert (await base.sources.rebuild())["status"] == "complete"
    assert await base.vector_store.count() == 1
    await service.close()


async def test_bad_dimensions_fail_before_store_write(tmp_path):
    service = build_service(config(tmp_path))
    base = service.knowledge_bases.runtime("default")
    service.embedder.embed_documents = AsyncMock(return_value=[[1.0]])
    with pytest.raises(EmbeddingError):
        await base.indexing_pipeline.index([Document(content="bad response")])
    assert await base.vector_store.count() == 0
    assert base.index_state.manifest()["state"] == "failed"
    await service.close()


async def test_remote_batches_reorders_results_and_never_exposes_key(tmp_path):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [float(i), 0]} for i in reversed(range(len(body["input"])))
        ]})

    settings = config(tmp_path, embedding_mode="compatible", embedding_model="test-model",
                      embedding_api_key="secret-test", embedding_base_url="https://example.test/v1",
                      embedding_dimensions=2, embedding_batch_size=2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        embedder = CompatibleEmbedder(settings, client=client)
        assert await embedder.embed_documents(["a", "b", "c"]) == [[0, 0], [1, 0], [0, 0]]
        assert [len(call["input"]) for call in calls] == [2, 1]
    runtime = build_embedder(settings)
    assert "secret-test" not in json.dumps(runtime.fingerprint)
    await runtime.embedder.close()


@pytest.mark.parametrize("response", [
    {"data": [{"index": 0, "embedding": [1]}]},
    {"data": [{"index": 1, "embedding": [1, 2]}]},
    {"data": []},
])
async def test_invalid_remote_response_has_no_hash_fallback(tmp_path, response):
    settings = config(tmp_path, embedding_mode="compatible", embedding_model="test-model",
                      embedding_api_key="secret-test", embedding_base_url="https://example.test/v1",
                      embedding_dimensions=2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response)
    )) as client:
        with pytest.raises(EmbeddingError):
            await CompatibleEmbedder(settings, client=client).embed_query("test")


def test_factory_unknown_modes_and_missing_credentials(tmp_path):
    with pytest.raises(ValueError, match="Unknown"):
        build_embedder(config(tmp_path, embedding_mode="missing"))
    with pytest.raises(ValueError):
        build_embedder(config(tmp_path, embedding_mode="compatible"))
    with pytest.raises(ValueError, match="Unknown"):
        build_vector_store(config(tmp_path, vector_backend="missing"))
    assert build_embedder(config(tmp_path, embedding_mode="auto")).active_mode == "hash"


@pytest.mark.parametrize("changed", [{"embedding_model": "model-b"},
                                   {"embedding_api_key": None}])
async def test_auto_never_reuses_existing_remote_vectors_with_another_model(tmp_path, changed):
    initial = config(tmp_path, embedding_mode="auto", embedding_model="model-a",
                     embedding_api_key="test-only", embedding_base_url="https://example.test/v1")
    first = build_service(initial)
    first.embedder.embed_documents = AsyncMock(return_value=[[0.0] * 16])
    await first.knowledge_bases.runtime("default").indexing_pipeline.index([Document(content="text")])
    await first.close()
    second = build_service(initial.model_copy(update=changed))
    runtime = second.knowledge_bases.runtime('default')
    if changed.get('embedding_model'):
        assert runtime.embedder.config.embedding_model == 'model-a'
        runtime.embedder.embed_query = AsyncMock(return_value=[0.0] * 16)
        assert len((await runtime.retriever.retrieve(Query(text='text'))).final_context) == 1
    else:
        with pytest.raises(IndexCompatibilityError):
            await runtime.retriever.retrieve(Query(text='text'))
    await second.close()


async def test_query_waits_for_write_and_sees_only_completed_index(tmp_path):
    service = build_service(config(tmp_path))
    runtime = service.knowledge_bases.runtime("default")
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.embedder.embed_documents

    async def slow_embed(texts):
        entered.set()
        await release.wait()
        return await original(texts)

    service.embedder.embed_documents = slow_embed
    writing = asyncio.create_task(runtime.indexing_pipeline.index([Document(content="alpha")]))
    await entered.wait()
    reading = asyncio.create_task(runtime.retriever.retrieve(Query(text="alpha")))
    await asyncio.sleep(0)
    assert not reading.done()
    release.set()
    await writing
    assert len((await reading).final_context) == 1
    await service.close()


async def test_failed_primary_keyword_write_blocks_manifest(tmp_path):
    service = build_service(config(tmp_path))
    runtime = service.knowledge_bases.runtime("default")
    runtime.keyword_store.upsert_strict = AsyncMock(side_effect=ConnectionError("private"))
    with pytest.raises(ConnectionError):
        await runtime.indexing_pipeline.index([Document(content="alpha")])
    assert runtime.index_state.manifest()["state"] == "failed"
    with pytest.raises(IndexCompatibilityError):
        await runtime.retriever.retrieve(Query(text="alpha"))
    await service.close()
