"""Freeze the applied configuration and evaluation inputs before any case executes."""
import hashlib
import json
from copy import deepcopy
from time import time
from uuid import uuid4


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def evaluation_snapshot(base, request, kind, concurrency):
    snapshot = deepcopy(base or {})
    snapshot.update(snapshot_id=str(uuid4()), captured_at=time(), snapshot_schema_version=1)
    snapshot['evaluation'] = {
        'kind': kind, 'k': request.k, 'knowledge_base_id': request.knowledge_base_id,
        'dataset_id': request.dataset_id, 'case_count': len(request.cases),
        'include_trace': request.include_trace, 'concurrency': concurrency,
        'cases_hash': digest([case.model_dump(mode='json') for case in request.cases]),
    }
    snapshot['snapshot_hash'] = digest(snapshot)
    return snapshot
