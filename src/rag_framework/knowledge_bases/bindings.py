"""Persist non-secret embedding profiles independently of process-wide settings."""

import json
import sqlite3
from pathlib import Path

from rag_framework.config import Settings
from rag_framework.contracts.providers import Embedder
from rag_framework.core.vectors import EmbeddingError
from rag_framework.presets import export_preset, validate_preset
from rag_framework.providers.embedding_factory import EmbeddingRuntime, build_embedder

EMBEDDING_FIELDS = {name for name in Settings.model_fields
                    if name.startswith('embedding_') and name != 'embedding_api_key'}


class UnavailableEmbedder(Embedder):
    async def embed_documents(self, texts):
        raise EmbeddingError('知识库绑定的嵌入配置不可用，请检查模型与密钥引用')

    async def embed_query(self, text):
        raise EmbeddingError('知识库绑定的嵌入配置不可用，请检查模型与密钥引用')


def bound_embedder(settings: Settings, profile: dict | None):
    try:
        return build_embedder(settings)
    except ValueError:
        if not profile:
            raise
        return EmbeddingRuntime(UnavailableEmbedder(), {}, settings.embedding_mode,
                                'unavailable', 'Bound embedding configuration unavailable')


def embedding_profile(settings: Settings, active_mode: str | None = None) -> dict:
    preset = export_preset(settings)
    values = {name: preset.settings[name] for name in EMBEDDING_FIELDS}
    if active_mode:
        values['embedding_mode'] = active_mode
    return {'schema_version': 1, 'settings': values,
            'secret_refs': {'embedding_api_key':
                            preset.secret_refs.get('embedding_api_key', 'RAG_EMBEDDING_API_KEY')}}


def profile_settings(base: Settings, profile: dict) -> Settings:
    preset = validate_preset(profile, Settings.model_fields)
    if set(preset.settings) - EMBEDDING_FIELDS or set(preset.secret_refs) - {'embedding_api_key'}:
        raise ValueError('知识库只能绑定嵌入配置；密钥必须使用环境变量引用')
    values = base.model_dump()
    values.update(preset.settings)
    reference = preset.secret_refs.get('embedding_api_key', 'RAG_EMBEDDING_API_KEY')
    from rag_framework.credentials import resolve_credential
    values['embedding_api_key'] = resolve_credential(base, 'embedding_api_key', reference)
    try:
        return Settings(_env_file=None, **values)
    except ValueError:
        raise ValueError('嵌入配置校验失败，请检查模式、维度及参数范围') from None


class BindingStore:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / 'catalog.sqlite3'
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE IF NOT EXISTS embedding_bindings '
                       '(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    def get(self, key):
        with sqlite3.connect(self.database) as db:
            row = db.execute('SELECT payload FROM embedding_bindings WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, key, profile):
        with sqlite3.connect(self.database) as db:
            db.execute('INSERT OR REPLACE INTO embedding_bindings VALUES (?,?)',
                       (key, json.dumps(profile, ensure_ascii=False)))

    def delete(self, key):
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM embedding_bindings WHERE id=?', (key,))
