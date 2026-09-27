"""Knowledge-base catalog and isolated retrieval runtimes."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import time
from uuid import uuid4

from pydantic import BaseModel

from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.pipeline.indexing import IndexingPipeline
from rag_framework.pipeline.retrieval import AdaptiveRetriever
from rag_framework.sources.service import SourceService


class KnowledgeBase(BaseModel):
    id: str
    name: str
    created_at: float


@dataclass
class KnowledgeBaseRuntime:
    vector_store: object
    keyword_store: object
    indexing_pipeline: IndexingPipeline
    retriever: AdaptiveRetriever
    generation_pipeline: GenerationPipeline
    sources: SourceService


class KnowledgeBaseManager:
    def __init__(self, directory: Path, default_runtime: KnowledgeBaseRuntime,
                 runtime_factory: Callable[[str], KnowledgeBaseRuntime]) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "catalog.sqlite3"
        self._runtime_factory = runtime_factory
        self._runtimes = {"default": default_runtime}
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS knowledge_bases "
                       "(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL)")
            db.execute("INSERT OR IGNORE INTO knowledge_bases VALUES (?,?,?)",
                       ("default", "默认知识库", time()))

    def list(self) -> list[KnowledgeBase]:
        with sqlite3.connect(self.database) as db:
            rows = db.execute("SELECT id,name,created_at FROM knowledge_bases ORDER BY created_at").fetchall()
        return [KnowledgeBase(id=row[0], name=row[1], created_at=row[2]) for row in rows]

    def get(self, knowledge_base_id: str) -> KnowledgeBase:
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT id,name,created_at FROM knowledge_bases WHERE id=?",
                             (knowledge_base_id,)).fetchone()
        if row is None:
            raise KeyError(knowledge_base_id)
        return KnowledgeBase(id=row[0], name=row[1], created_at=row[2])

    def create(self, name: str) -> KnowledgeBase:
        item = KnowledgeBase(id=uuid4().hex[:12], name=name.strip(), created_at=time())
        if not item.name:
            raise ValueError("知识库名称不能为空")
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO knowledge_bases VALUES (?,?,?)",
                       (item.id, item.name, item.created_at))
        return item

    def runtime(self, knowledge_base_id: str) -> KnowledgeBaseRuntime:
        self.get(knowledge_base_id)
        if knowledge_base_id not in self._runtimes:
            self._runtimes[knowledge_base_id] = self._runtime_factory(knowledge_base_id)
        return self._runtimes[knowledge_base_id]

    async def describe(self, knowledge_base_id: str) -> dict:
        item = self.get(knowledge_base_id)
        runtime = self.runtime(knowledge_base_id)
        return {**item.model_dump(), **runtime.sources.stats(),
                "vector_chunks": await runtime.vector_store.count(),
                "keyword_chunks": await runtime.keyword_store.count()}

    async def close(self) -> None:
        for runtime in self._runtimes.values():
            close = getattr(runtime.keyword_store, "close", None)
            if close is not None:
                await close()
