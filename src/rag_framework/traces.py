"""Durable API traces and task-local capture of partial execution."""

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from time import time

from rag_framework.core.models import RetrievalTrace

current_trace: ContextVar[RetrievalTrace | None] = ContextVar('request_trace', default=None)


class TraceStore:
    def __init__(self, path, limit=1000):
        self.path = path
        self.limit = limit

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                connection.execute('CREATE TABLE IF NOT EXISTS traces '
                    '(id TEXT PRIMARY KEY, conversation TEXT, started REAL, payload TEXT)')
                yield connection
        finally:
            connection.close()

    def save(self, trace, answer=None):
        payload = {'trace': trace.model_dump(mode='json'), 'answer': answer}
        with self.connect() as connection:
            connection.execute('INSERT OR REPLACE INTO traces VALUES (?, ?, ?, ?)',
                (trace.id, trace.query.conversation_id, trace.started_at,
                 json.dumps(payload, ensure_ascii=False, allow_nan=False)))
            connection.execute('DELETE FROM traces WHERE id IN '
                '(SELECT id FROM traces ORDER BY started DESC LIMIT -1 OFFSET ?)', (self.limit,))

    def get(self, trace_id):
        with self.connect() as connection:
            row = connection.execute('SELECT payload FROM traces WHERE id=?', (trace_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, conversation_id=None, limit=100):
        with self.connect() as connection:
            rows = connection.execute(
                'SELECT payload FROM traces WHERE (? IS NULL OR conversation=?) '
                'ORDER BY started DESC LIMIT ?', (conversation_id, conversation_id, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]


@asynccontextmanager
async def capture(store, query):
    trace = RetrievalTrace(query=query)
    token = current_trace.set(trace)
    try:
        await asyncio.to_thread(store.save, trace)
        yield trace
    except BaseException as exc:
        trace.status = 'failed'
        trace.error = type(exc).__name__
        trace.add_step('execution_error', 0, error=type(exc).__name__)
        trace.finished_at = time()
        await asyncio.to_thread(store.save, trace)
        raise
    finally:
        current_trace.reset(token)


async def complete(store, trace, answer=None):
    trace.status = 'completed'
    trace.finished_at = time()
    await asyncio.to_thread(store.save, trace, answer)
