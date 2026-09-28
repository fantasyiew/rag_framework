"""Versioned presets and safe, deterministic configuration snapshots."""

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

SECRET_FIELDS = {
    "embedding_api_key", "planner_api_key", "generation_api_key",
    "evaluation_judge_api_key", "reranker_cloud_api_key",
    "elasticsearch_api_key", "elasticsearch_password", "elasticsearch_username",
}


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=1, ge=1, le=1)
    settings: dict = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)


def validate_preset(data, fields):
    preset = Preset.model_validate(data)
    if set(preset.settings) - (set(fields) - SECRET_FIELDS - {"service_preset"}):
        raise ValueError("Preset contains unknown, secret or recursive settings")
    if set(preset.secret_refs) - SECRET_FIELDS:
        raise ValueError("Preset secret_refs must target credential fields")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in preset.secret_refs.values()):
        raise ValueError("Secret references must be environment variable names")
    for name, value in preset.settings.items():
        if name.endswith(("_url", "_base_url")) and value and safe_url(value) != value:
            raise ValueError("Preset URLs must not contain credentials, query or fragment")
    return preset


def safe_url(value):
    parsed = urlsplit(value)
    host = parsed.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def preset_source(settings_cls, init, env, dotenv):
    # Native Pydantic priority remains init > env > dotenv > preset > defaults.
    selection = {**dotenv(), **env(), **init()}
    path = selection.get("service_preset")
    if not path:
        return {}
    try:
        preset = validate_preset(json.loads(Path(path).read_text(encoding="utf-8-sig")),
                                 settings_cls.model_fields)
    except (OSError, ValueError, TypeError):
        raise ValueError("Cannot load preset: invalid path, schema or settings") from None
    values = dict(preset.settings)
    for field, variable in preset.secret_refs.items():
        if field in selection:
            continue
        if variable not in os.environ:
            raise ValueError(f"Missing preset credential environment variable: {variable}")
        values[field] = os.environ[variable]
    return values


def export_preset(settings):
    values = settings.model_dump(mode="json", exclude=SECRET_FIELDS | {"service_preset"})
    serialized = json.dumps(values, ensure_ascii=False)
    for name in SECRET_FIELDS:
        secret = getattr(settings, name, None)
        secret = secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
        if secret and secret in serialized:
            raise ValueError("Sensitive value appears outside credential fields")
    references = {name: "RAG_" + name.upper() for name in SECRET_FIELDS
                  if getattr(settings, name, None) is not None}
    return validate_preset({"schema_version": 1, "settings": values, "secret_refs": references},
                           type(settings).model_fields)


def config_snapshot(settings):
    values = settings.model_dump(mode="json", exclude=SECRET_FIELDS | {"service_preset"})
    # Endpoint credentials are excluded even if legacy environment configuration contains them.
    for name, value in values.items():
        if name.endswith(("_url", "_base_url")) and value:
            values[name] = safe_url(value)
    known = [getattr(settings, name, None) for name in SECRET_FIELDS]
    known = [value.get_secret_value() if hasattr(value, "get_secret_value") else value
             for value in known if value]
    def redact(value):
        if isinstance(value, str):
            for secret in known:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {k: redact(v) for k, v in value.items()}
        return value
    values = redact(values)
    payload = {"schema_version": 1, "settings": values}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode()).hexdigest()
    return {**payload, "config_hash": digest}
