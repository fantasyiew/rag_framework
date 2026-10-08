"""Knowledge-base catalog and isolated retrieval runtimes."""

import asyncio
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import time
from uuid import uuid4

from pydantic import BaseModel

from rag_framework.contracts.lifecycle import AsyncClosable
from rag_framework.index_state import IndexCompatibilityError, IndexState
from rag_framework.knowledge_bases.bindings import embedding_profile
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.pipeline.indexing import IndexingPipeline
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.providers.embedding_factory import build_embedder
from rag_framework.sources.service import SourceService


class KnowledgeBase(BaseModel):
    id: str
    name: str
    created_at: float
    status: str = 'active'


@dataclass
class KnowledgeBaseRuntime:
    vector_store: object
    keyword_store: object
    indexing_pipeline: IndexingPipeline
    retriever: AdaptiveRetriever
    generation_pipeline: GenerationPipeline
    sources: SourceService
    index_state: IndexState | None = None
    embedder: object = None


class KnowledgeBaseManager:
    def __init__(self, directory: Path, default_runtime: KnowledgeBaseRuntime,
                 runtime_factory: Callable[[str], KnowledgeBaseRuntime]) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "catalog.sqlite3"
        self._runtime_factory = runtime_factory
        self._runtimes = {"default": default_runtime}
        self.operation_lock = asyncio.Lock()
        self.bindings = None
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS knowledge_bases "
                       "(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL)")
            if 'status' not in {row[1] for row in db.execute('PRAGMA table_info(knowledge_bases)')}:
                db.execute("ALTER TABLE knowledge_bases ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            db.execute("INSERT OR IGNORE INTO knowledge_bases (id,name,created_at) VALUES (?,?,?)",
                       ("default", "默认知识库", time()))

    def list(self) -> list[KnowledgeBase]:
        with sqlite3.connect(self.database) as db:
            rows = db.execute("SELECT id,name,created_at,status FROM knowledge_bases "
                              "WHERE status!='deleted' ORDER BY created_at").fetchall()
        return [KnowledgeBase(id=row[0], name=row[1], created_at=row[2], status=row[3]) for row in rows]

    def get(self, knowledge_base_id: str) -> KnowledgeBase:
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT id,name,created_at,status FROM knowledge_bases WHERE id=?",
                             (knowledge_base_id,)).fetchone()
        if row is None:
            raise KeyError(knowledge_base_id)
        return KnowledgeBase(id=row[0], name=row[1], created_at=row[2], status=row[3])

    def create(self, name: str, profile: dict | None = None) -> KnowledgeBase:
        if self.bindings:
            profile = profile or self.default_profile()
            config = self.validate_profile(profile)
            normalized = embedding_profile(config, ('compatible' if config.embedding_api_key else 'hash')
                if config.embedding_mode == 'auto' else config.embedding_mode)
            normalized['secret_refs'] = profile.get('secret_refs', normalized['secret_refs'])
            profile = normalized
        item = KnowledgeBase(id=uuid4().hex[:12], name=name.strip(), created_at=time())
        if not item.name:
            raise ValueError("知识库名称不能为空")
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO knowledge_bases (id,name,created_at) VALUES (?,?,?)",
                       (item.id, item.name, item.created_at))
        if self.bindings:
            self.bindings.save(item.id, profile)
        return item

    def runtime(self, knowledge_base_id: str) -> KnowledgeBaseRuntime:
        item = self.get(knowledge_base_id)
        if item.status != 'active':
            raise IndexCompatibilityError('知识库已弃用或删除，请恢复或切换到其他知识库')
        return self._load_runtime(knowledge_base_id)

    def _load_runtime(self, knowledge_base_id):
        if knowledge_base_id not in self._runtimes:
            self._runtimes[knowledge_base_id] = self._runtime_factory(knowledge_base_id)
            if self.get(knowledge_base_id).status != 'active' and self._runtimes[knowledge_base_id].index_state:
                self._runtimes[knowledge_base_id].index_state.access_blocked = '知识库已弃用'
        return self._runtimes[knowledge_base_id]

    async def describe(self, knowledge_base_id: str) -> dict:
        item = self.get(knowledge_base_id)
        if item.status == 'deleted':
            raise KeyError(knowledge_base_id)
        try:
            runtime = self._load_runtime(knowledge_base_id)
        except Exception as exc:  # noqa: BLE001 - Invalid credentials must not hide the catalog.
            return {**item.model_dump(), 'embedding_binding': self.bindings.get(item.id) if self.bindings else None,
                    'index': {'status': 'unavailable', 'reason': type(exc).__name__}}
        counts, errors = {}, {}
        for name, store in (("vector_chunks", runtime.vector_store), ("keyword_chunks", runtime.keyword_store)):
            try:
                counts[name] = await store.count()
            except Exception as exc:  # noqa: BLE001 - Admin must remain available during outages.
                counts[name] = None
                errors[name] = type(exc).__name__
        index = await runtime.index_state.describe() if runtime.index_state else None
        if self.bindings and not self.bindings.get(item.id) and index and index['status'] == 'empty':
            self.bindings.save(item.id, self.default_profile())
        return {**item.model_dump(), **runtime.sources.stats(),
                'embedding_binding': self.bindings.get(item.id) if self.bindings else None,
                "index": index,
                **counts, "count_errors": errors}

    def _set_status(self, key, status):
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE knowledge_bases SET status=? WHERE id=?', (status, key))

    async def set_archived(self, key: str, archived: bool):
        async with self.operation_lock:
            item = self.get(key)
            if key == 'default' or item.status == 'deleted':
                raise ValueError('默认知识库不能弃用或删除；已删除知识库不能恢复')
            runtime = self._runtimes.get(key)
            if runtime and runtime.index_state:
                async with runtime.sources.lock, runtime.index_state.lock:
                    runtime.index_state.access_blocked = '知识库已弃用' if archived else None
                    self._set_status(key, 'archived' if archived else 'active')
            else:
                self._set_status(key, 'archived' if archived else 'active')
        return await self.describe(key)

    async def bind(self, key: str, profile: dict, rebuild: bool = False):
        async with self.operation_lock:
            self.runtime(key)
            config = self.validate_profile(profile)
            candidate = build_embedder(config)
            try:
                normalized = embedding_profile(config, candidate.active_mode)
                normalized['secret_refs'] = profile.get('secret_refs', normalized['secret_refs'])
            finally:
                if isinstance(candidate.embedder, AsyncClosable):
                    await candidate.embedder.close()
            old_profile = self.bindings.get(key)
            old_runtime = self._runtimes[key]
            state = old_runtime.index_state
            async with old_runtime.sources.lock, state.lock:
                manifest = state.manifest()
                indexed = await old_runtime.vector_store.count() or await old_runtime.keyword_store.count()
                if indexed and (not manifest or manifest.get('fingerprint', {}).get('embedding') != candidate.fingerprint) and not rebuild:
                    raise ValueError('嵌入模型与已有索引不一致，必须明确确认重建')
                state.access_blocked = '知识库模型正在切换，请稍后重试'
                await self._close_runtime(old_runtime)
                self._runtimes.pop(key)
                self.bindings.save(key, normalized)
                try:
                    runtime = self._load_runtime(key)
                except Exception:
                    if old_profile:
                        self.bindings.save(key, old_profile)
                    else:
                        self.bindings.delete(key)
                    raise
            if hasattr(self, 'on_runtime_change'):
                self.on_runtime_change(key)
            if rebuild:
                result = await runtime.sources.rebuild()
                if result.get('status') != 'complete':
                    return {**await self.describe(key), 'rebuild': result}
            return {**await self.describe(key), 'rebuild': result if rebuild else None}

    async def delete(self, key: str, confirmation_name: str):
        async with self.operation_lock:
            item = self.get(key)
            if key == 'default':
                raise ValueError('默认知识库不能删除，请使用清空功能')
            if confirmation_name != item.name:
                raise ValueError('请准确输入知识库名称以确认永久删除')
            if item.status == 'deleted':
                return {'id': key, 'status': 'deleted'}
            target = (self.directory / key).resolve()
            if target.parent != self.directory.resolve() or not key.isalnum():
                raise ValueError('知识库目录不合法')
            runtime = self._load_runtime(key)
            async with runtime.sources.lock, runtime.index_state.lock:
                manifest = runtime.index_state.manifest() or {'schema_version': 1}
                recorded = manifest.get('fingerprint') or {}
                expected = runtime.index_state.fingerprint
                if any(recorded.get(name) and recorded[name] != expected[name] for name in ('vector', 'keyword')):
                    raise ValueError('索引存储配置与创建时不一致，请恢复原存储配置后删除，避免遗留索引')
                if expected['keyword']['backend'] == 'elasticsearch' and not hasattr(runtime.keyword_store, 'primary'):
                    raise ValueError('Elasticsearch 管理客户端不可用，拒绝仅删除本地数据')
                runtime.index_state.save({**manifest, 'state': 'building', 'operation': 'delete'})
                runtime.index_state.access_blocked = '知识库正在永久删除'
                self._set_status(key, 'archived')
                try:
                    for store in (runtime.keyword_store, runtime.vector_store):
                        await (store.delete_index() if hasattr(store, 'delete_index') else store.clear())
                    await self._close_runtime(runtime)
                    if target.exists():
                        await asyncio.to_thread(shutil.rmtree, target)
                except Exception:
                    runtime.index_state.access_blocked = '删除未完成，请重试删除或恢复后重建'
                    self._runtimes.pop(key, None)
                    try:
                        await self._close_runtime(runtime)
                    except Exception:  # noqa: BLE001, S110 - Preserve the original deletion failure.
                        pass
                    raise
                self._runtimes.pop(key, None)
                if self.bindings:
                    self.bindings.delete(key)
                self._set_status(key, 'deleted')
            return {'id': key, 'status': 'deleted', 'traces_preserved': True}

    async def _close_runtime(self, runtime):
        for store in (runtime.keyword_store, runtime.vector_store, runtime.embedder):
            if isinstance(store, AsyncClosable):
                await store.close()

    async def close(self) -> None:
        errors = []
        for runtime in self._runtimes.values():
            for store in (runtime.keyword_store, runtime.vector_store, runtime.embedder):
                if isinstance(store, AsyncClosable):
                    try:
                        await store.close()
                    except Exception as exc:  # noqa: BLE001 - Close all resources before reporting.
                        errors.append(exc)
        if errors:
            raise ExceptionGroup("Store shutdown failures", errors)
