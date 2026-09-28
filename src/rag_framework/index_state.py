"""Persistent index identity and a recoverable, single-process operation journal."""

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from time import time

from rag_framework.core.models import Document


class IndexCompatibilityError(RuntimeError):
    pass


class IndexState:
    def __init__(self, directory: Path, fingerprint: dict, vector_store, keyword_store):
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "index-state.sqlite3"
        self.source_catalog = directory / "catalog.sqlite3"
        self.fingerprint = fingerprint
        self.vector_store = vector_store
        self.keyword_store = keyword_store
        self.lock = asyncio.Lock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS manifest (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS canonical_documents (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database)
        try:
            with db:
                yield db
        finally:
            db.close()

    def manifest(self):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM manifest WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def save(self, manifest):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO manifest VALUES (1,?)",
                       (json.dumps(manifest, ensure_ascii=False, allow_nan=False),))

    def documents(self):
        with self.connect() as db:
            return [Document.model_validate_json(row[0]) for row in
                    db.execute("SELECT payload FROM canonical_documents")]

    def begin(self, operation: str, documents: list[Document]):
        old = self.manifest() or {}
        manifest = {
            "schema_version": 1, "state": "building", "operation": operation,
            "fingerprint": old.get("fingerprint"), "pending_fingerprint": self.fingerprint,
            "created_at": old.get("created_at", time()),
            "updated_at": time(),
        }
        # Persist recovery input before any index mutation.
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO manifest VALUES (1,?)", (json.dumps(manifest),))
            for document in documents:
                db.execute("INSERT OR REPLACE INTO canonical_documents VALUES (?,?)",
                           (document.id, document.model_dump_json()))

    def complete(self):
        self.save({"schema_version": 1, "state": "ready",
                   "created_at": (self.manifest() or {}).get("created_at", time()),
                   "fingerprint": self.fingerprint, "updated_at": time()})

    def fail(self, error: Exception):
        manifest = self.manifest() or {"schema_version": 1}
        manifest.update(state="failed", error=type(error).__name__, updated_at=time())
        self.save(manifest)

    async def validate(self):
        manifest = self.manifest()
        if manifest is not None:
            if manifest.get("schema_version") != 1 or manifest.get("state") != "ready":
                raise IndexCompatibilityError("索引正在重建或上次操作失败，请显式重建知识库")
            if manifest.get("fingerprint") != self.fingerprint:
                raise IndexCompatibilityError("索引的模型、维度、分块或存储配置不兼容，请显式重建知识库")
            return
        has_catalog = False
        if self.source_catalog.exists():
            with sqlite3.connect(self.source_catalog) as db:
                has_catalog = bool(db.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        if (has_catalog or self.documents() or await self.vector_store.count()
                or await self.keyword_store.count()):
            raise IndexCompatibilityError("旧索引没有指纹，不能确认模型身份；请从原始数据显式重建")

    async def describe(self):
        try:
            await self.validate()
            return {"status": "ready" if self.manifest() else "empty",
                    "manifest": self.manifest(), "expected": self.fingerprint}
        except IndexCompatibilityError as exc:
            return {"status": "blocked", "reason": str(exc), "manifest": self.manifest(),
                    "expected": self.fingerprint}
        except Exception as exc:  # noqa: BLE001 - Keep admin available during provider outages.
            return {"status": "unavailable", "reason": type(exc).__name__}
