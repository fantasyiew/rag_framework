"""Local source archive and canonical document catalog for single-worker ingestion."""

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from time import time
from uuid import uuid4

from rag_framework.contracts.lifecycle import IndexAdmin, RecoverableIndex
from rag_framework.core.models import Document
from rag_framework.index_state import IndexCompatibilityError
from rag_framework.pipeline.indexing import IndexingPipeline

from .adapters import AdapterOptions, digest, registry


class SourceService:
    def __init__(self, directory: Path, pipeline: IndexingPipeline):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / 'catalog.sqlite3'
        self.pipeline = pipeline
        self.lock = asyncio.Lock()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, name TEXT, kind TEXT, checksum TEXT,
                    size INTEGER, inspection TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, source_id TEXT, payload TEXT);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, source_id TEXT, payload TEXT);
            ''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def upload(self, data: bytes, name: str, kind: str):
        inspection = registry.get(kind).inspect(data)
        source_id = uuid4().hex
        (self.directory / source_id).write_bytes(data)
        with self.connect() as db:
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?)',
                       (source_id, name, kind, digest(data), len(data), json.dumps(inspection), time()))
        return self.get(source_id)

    def get(self, source_id: str):
        with self.connect() as db:
            row = db.execute('SELECT * FROM sources WHERE id=?', (source_id,)).fetchone()
        if not row:
            raise KeyError(source_id)
        return dict(zip(['id', 'name', 'kind', 'checksum', 'size', 'inspection', 'created'],
                        [*row[:5], json.loads(row[5]), row[6]], strict=True))

    def list_sources(self):
        with self.connect() as db:
            ids = db.execute('SELECT id FROM sources ORDER BY created DESC').fetchall()
        return [self.get(row[0]) for row in ids]

    def prepare(self, source_id: str, options: AdapterOptions):
        source = self.get(source_id)
        data = (self.directory / source['id']).read_bytes()
        documents = registry.get(source['kind']).documents(data, options)
        for document in documents:
            # Names and upload IDs are provenance, not document identity.
            identity = json.dumps({'kind': source['kind'], 'content': document.content,
                                   'metadata': document.metadata}, sort_keys=True, ensure_ascii=False)
            document.id = digest(identity.encode())
            document.source_uri = f'source://{source_id}'
            document.metadata.update({'file_name': source['name'], 'source_id': source_id,
                                      'source_checksum': source['checksum']})
        return documents

    def list_documents(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT payload FROM documents')]

    def get_document(self, document_id: str):
        with self.connect() as db:
            row = db.execute(
                'SELECT payload FROM documents WHERE id=?', (document_id,)
            ).fetchone()
        if row is None:
            raise KeyError(document_id)
        return json.loads(row[0])

    def list_runs(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT payload FROM runs ORDER BY rowid DESC')]

    def stats(self):
        with self.connect() as db:
            source_count = db.execute('SELECT COUNT(*) FROM sources').fetchone()[0]
            document_count = db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
            run_count = db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
        return {'sources': source_count, 'documents': document_count, 'runs': run_count}

    def save_run(self, run):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO runs VALUES (?,?,?)',
                       (run['id'], run['source_id'], json.dumps(run, ensure_ascii=False)))

    async def ingest(self, source_id: str, options: AdapterOptions):
        async with self.lock:
            if isinstance(self.pipeline, RecoverableIndex):
                await self.pipeline.check_index()
            return await self._ingest_unlocked(source_id, options)

    async def _ingest_unlocked(self, source_id: str, options: AdapterOptions):
        documents = self.prepare(source_id, options)
        run = {'id': uuid4().hex, 'source_id': source_id, 'started_at': time(),
                   'source': self.get(source_id), 'options': options.model_dump(),
                   'status': 'running', 'received_documents': len(documents),
                   'created_documents': 0, 'skipped_documents': 0, 'created_chunks': 0,
                   'chunk_size': self.pipeline.chunker.parameters.get('chunk_size'),
                   'overlap': self.pipeline.chunker.parameters.get('overlap'),
                   'chunker': type(self.pipeline.chunker).__name__,
                   'chunker_parameters': self.pipeline.chunker.parameters,
                   'embedder': type(self.pipeline.embedder).__name__}
        self.save_run(run)
        try:
            for document in documents:
                with self.connect() as db:
                    exists = db.execute('SELECT 1 FROM documents WHERE id=?', (document.id,)).fetchone()
                if exists:
                    run['skipped_documents'] += 1
                    continue
                chunks = await self.pipeline.index([document])
                with self.connect() as db:
                    db.execute('INSERT INTO documents VALUES (?,?,?)',
                               (document.id, source_id, document.model_dump_json()))
                run['created_documents'] += 1
                run['created_chunks'] += len(chunks)
            run['status'] = 'complete'
        except Exception as exc:  # noqa: BLE001 - Persist failure without exposing provider secrets.
            run['status'] = 'failed'
            run['error'] = type(exc).__name__
        finally:
            run['finished_at'] = time()
            self.save_run(run)
        return run

    async def clear(self):
        """Clear derived retrieval state while preserving artifacts and audit runs."""
        async with self.lock:
            if isinstance(self.pipeline, RecoverableIndex):
                vector_chunks, keyword_chunks = await self.pipeline.clear_index()
            else:
                if not isinstance(self.pipeline.vector_store, IndexAdmin) or not isinstance(self.pipeline.keyword_store, IndexAdmin):
                    raise TypeError('Configured stores do not support clearing')
                vector_chunks = await self.pipeline.vector_store.clear()
                keyword_chunks = await self.pipeline.keyword_store.clear()
            with self.connect() as db:
                document_count = db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
                db.execute('DELETE FROM documents')
            run = {
                'id': uuid4().hex, 'source_id': '', 'operation': 'clear',
                'started_at': time(), 'finished_at': time(), 'status': 'complete',
                'deleted_documents': document_count,
                'deleted_vector_chunks': vector_chunks,
                'deleted_keyword_chunks': keyword_chunks,
                'preserved_sources': self.stats()['sources'],
            }
            self.save_run(run)
            return run

    async def rebuild(self):
        """Recreate all derived documents and indexes from successful ingest recipes."""
        async with self.lock:
            if isinstance(self.pipeline, RecoverableIndex):
                return await self._rebuild_managed()
            recipes: list[tuple[str, AdapterOptions]] = []
            seen: set[tuple[str, str]] = set()
            for run in self.list_runs():
                if run.get('operation', 'ingest') != 'ingest' or run.get('status') != 'complete':
                    continue
                source_id = run.get('source_id')
                options_payload = run.get('options') or {}
                key = (source_id, json.dumps(options_payload, sort_keys=True))
                if source_id and key not in seen:
                    recipes.append((source_id, AdapterOptions.model_validate(options_payload)))
                    seen.add(key)

            if not isinstance(self.pipeline.vector_store, IndexAdmin) or not isinstance(self.pipeline.keyword_store, IndexAdmin):
                raise TypeError('Configured stores do not support rebuilding')
            await self.pipeline.vector_store.clear()
            await self.pipeline.keyword_store.clear()
            with self.connect() as db:
                db.execute('DELETE FROM documents')

            results = []
            for source_id, options in reversed(recipes):
                results.append(await self._ingest_unlocked(source_id, options))
            return {
                'status': 'complete' if all(item['status'] == 'complete' for item in results) else 'partial',
                'recipes': len(recipes),
                'runs': results,
                'documents': self.stats()['documents'],
            }

    async def _rebuild_managed(self):
        run = {'id': uuid4().hex, 'source_id': '', 'operation': 'rebuild',
               'status': 'running', 'started_at': time()}
        self.save_run(run)
        try:
            # Resolve every input before clearing; keep canonical documents on all failures.
            documents = {d.id: d for d in self.pipeline.canonical_documents()}
            documents.update({d['id']: Document.model_validate(d) for d in self.list_documents()})
            recipes = set()
            for previous in self.list_runs():
                if previous.get('operation', 'ingest') != 'ingest' or previous.get('status') != 'complete':
                    continue
                key = (previous['source_id'], json.dumps(previous['options'], sort_keys=True))
                if key in recipes:
                    continue
                recipes.add(key)
                for document in self.prepare(previous['source_id'], AdapterOptions.model_validate(previous['options'])):
                    documents.setdefault(document.id, document)
            chunks = await self.pipeline.rebuild_documents(list(documents.values()))
            documents = {document.id: document for document in self.pipeline.canonical_documents()}
            with self.connect() as db:
                db.execute('DELETE FROM documents')
                for document in documents.values():
                    db.execute('INSERT INTO documents VALUES (?,?,?)',
                               (document.id, document.metadata.get('source_id', ''), document.model_dump_json()))
            run.update(status='complete', documents=len(documents), recipes=len(recipes),
                       created_chunks=len(chunks), runs=[])
        except Exception as exc:  # noqa: BLE001 - Persist failures for recovery without provider secrets.
            run.update(status='failed', error=type(exc).__name__,
                       documents=self.stats()['documents'], recipes=0, runs=[])
            if isinstance(exc, IndexCompatibilityError):
                run['message'] = str(exc)
        finally:
            run['finished_at'] = time()
            self.save_run(run)
        return run
