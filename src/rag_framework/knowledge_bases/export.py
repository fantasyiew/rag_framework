"""Bounded-memory, locked chunk snapshots. No embeddings or credential settings."""
import asyncio
import hashlib
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from functools import lru_cache


async def prepare_export(manager, key):
    archive = tempfile.TemporaryFile(mode='w+b')  # noqa: SIM115 - Ownership passes to response.
    try:
        async with manager.operation_lock:
            item = manager.get(key)
            if item.status == 'deleted':
                raise KeyError(key)
            runtime = manager._load_runtime(key)
            async with runtime.sources.lock, runtime.index_state.lock:
                @lru_cache(maxsize=128)
                def raw_metadata(document_id):
                    with runtime.index_state.connect() as db:
                        record = db.execute('SELECT payload FROM canonical_documents WHERE id=?', (document_id,)).fetchone()
                    return json.loads(record[0]).get('metadata', {}).get('raw_metadata') if record else None
                binding = manager.bindings.get(key) if manager.bindings else None
                profile = binding.get('settings', {}) if binding else {}
                # Export only embedding identity, never connection/auth configuration.
                embedding = {field: profile.get('embedding_' + field)
                             for field in ('mode', 'model', 'dimensions', 'model_revision')}
                count, checksum = 0, hashlib.sha256()
                with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
                    with output.open('chunks.jsonl', 'w') as chunks:
                        async for chunk in runtime.vector_store.iter_chunks():
                            row = chunk.model_dump(mode='json')
                            original = raw_metadata(chunk.document_id)
                            if original is not None:
                                row['metadata']['raw_metadata'] = original
                            # Keep the full stored metadata, including raw_metadata encoding.
                            payload = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8')
                            await asyncio.to_thread(chunks.write, payload)
                            checksum.update(payload)
                            count += 1
                    manifest = {'schema_version': 1, 'export_kind': 'chunk_analysis_snapshot',
                        'knowledge_base': {'id': item.id, 'name': item.name, 'status': item.status},
                        'exported_at': datetime.now(UTC).isoformat(), 'chunk_count': count,
                        'embedding': embedding, 'index_manifest': runtime.index_state.manifest(),
                        'files': ['chunks.jsonl'], 'chunks_sha256': checksum.hexdigest(),
                        'includes_vectors': False,
                        'consistency': 'single_process_locked_snapshot'}
                    output.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.seek(0)
        return archive
    except BaseException:
        archive.close()
        raise


async def stream_archive(archive):
    try:
        while block := await asyncio.to_thread(archive.read, 64 * 1024):
            yield block
    finally:
        archive.close()
