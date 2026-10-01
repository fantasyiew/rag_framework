"""Single-worker configuration transactions and persisted safe overrides."""

import asyncio
import json
import os
import tempfile
from contextlib import asynccontextmanager

HOT_FIELDS = {
    'default_top_k', 'default_retrieval_strategy', 'default_retrieval_rerank',
    'fusion_mode', 'fusion_weights', 'fusion_normalization', 'fusion_rank_constant',
    'rrf_rank_constant', 'hybrid_candidate_multiplier', 'reranker_candidate_k',
    'planner_temperature', 'planner_request_timeout', 'planner_max_retries',
    'planner_minimum_confidence', 'planner_max_rewrites',
    'generation_temperature', 'generation_request_timeout', 'generation_max_retries',
    'generation_max_tokens', 'generation_max_context_chunks',
    'generation_system_prompt', 'generation_user_prompt',
    'evaluation_concurrency', 'evaluation_metrics', 'evaluation_judge_temperature',
    'evaluation_judge_request_timeout', 'evaluation_judge_max_retries',
    'evaluation_judge_max_tokens', 'evaluation_judge_max_context_characters',
}


def read_state(path):
    if not path.exists():
        return {'schema_version': 1, 'version': 0, 'settings': {}}
    state = json.loads(path.read_text(encoding='utf-8'))
    if (state.get('schema_version') != 1 or not isinstance(state.get('version'), int)
            or state['version'] < 0 or not isinstance(state.get('settings'), dict)
            or set(state['settings']) - HOT_FIELDS):
        raise ValueError('Invalid managed configuration file')
    return state


def isolated_settings(settings_type, values):
    class IsolatedSettings(settings_type):
        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, env_settings,
                                       dotenv_settings, file_secret_settings):
            return (init_settings,)
    return IsolatedSettings(_env_file=None, **values)


def load_managed_config(config):
    state = read_state(config.managed_config_path)
    values = config.model_dump()
    values.update(state['settings'])
    # Explicit values prevent environment variables from overriding applied hot settings.
    return isolated_settings(type(config), values)


def write_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.config-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump(state, output, ensure_ascii=False, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class RequestGate:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.readers = 0
        self.writing = False
        self.writer_lock = asyncio.Lock()

    @asynccontextmanager
    async def request(self):
        async with self.condition:
            await self.condition.wait_for(lambda: not self.writing)
            self.readers += 1
        try:
            yield
        finally:
            async with self.condition:
                self.readers -= 1
                self.condition.notify_all()

    @asynccontextmanager
    async def update(self):
        async with self.writer_lock:
            try:
                async with self.condition:
                    self.writing = True
                    await self.condition.wait_for(lambda: self.readers == 0)
                yield
            finally:
                async with self.condition:
                    self.writing = False
                    self.condition.notify_all()


class ConfigurationGateMiddleware:
    def __init__(self, app, gate):
        self.app, self.gate = app, gate

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path') == '/v1/config/apply':
            await self.app(scope, receive, send)
        else:
            async with self.gate.request():
                await self.app(scope, receive, send)
