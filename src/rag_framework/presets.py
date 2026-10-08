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


class PresetFieldError(ValueError):
    """Safe field-level failures: never include submitted values."""
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Invalid preset fields')


def validate_preset(data, fields):
    preset = Preset.model_validate(data)
    errors = []
    for name in sorted(set(preset.settings) - (set(fields) - SECRET_FIELDS - {'service_preset'})):
        message = ('凭据不能直接写入 settings，请使用 secret_refs 环境变量引用' if name in SECRET_FIELDS
                   else '不允许在预设中引用另一预设' if name == 'service_preset' else '未知配置字段')
        errors.append({'field': name, 'message': message})
    for field, reference in preset.secret_refs.items():
        if field not in SECRET_FIELDS:
            errors.append({'field': 'secret_refs.' + field, 'message': '此字段不是可引用的凭据字段'})
        elif not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', reference):
            errors.append({'field': field, 'message': '密钥引用必须是环境变量名：以字母或下划线开头，仅含字母、数字和下划线；不要填写密钥明文'})
    for name, value in preset.settings.items():
        if name.endswith(('_url', '_base_url')) and value:
            try:
                valid = isinstance(value, str) and safe_url(value) == value
            except (ValueError, TypeError, AttributeError):
                valid = False
            if not valid:
                errors.append({'field': name, 'message': 'URL 必须为字符串，且不能包含认证信息、查询参数或片段'})
    if errors:
        raise PresetFieldError(errors)
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
