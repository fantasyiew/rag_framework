import json

import pytest

from rag_framework.config import Settings
from rag_framework.presets import config_snapshot, export_preset, validate_preset


def test_preset_roundtrip_priority_and_secret_reference(tmp_path, monkeypatch):
    original = Settings(_env_file=None, chunk_size=600, planner_api_key="private-key")
    preset = export_preset(original)
    assert "private-key" not in preset.model_dump_json()
    path = tmp_path / "preset.json"
    path.write_text(preset.model_dump_json(), encoding="utf-8")
    monkeypatch.setenv("RAG_PLANNER_API_KEY", "private-key")
    restored = Settings(_env_file=None, service_preset=path)
    assert config_snapshot(original) == config_snapshot(restored)
    monkeypatch.setenv("RAG_CHUNK_SIZE", "700")
    assert Settings(_env_file=None, service_preset=path).chunk_size == 700
    assert Settings(_env_file=None, service_preset=path, chunk_size=800).chunk_size == 800


def test_dotenv_selects_preset_and_custom_env_reference(tmp_path, monkeypatch):
    path = tmp_path / "preset.json"
    path.write_text(json.dumps({"schema_version": 1, "settings": {"chunk_size": 500},
                               "secret_refs": {"planner_api_key": "CUSTOM_KEY"}}))
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"RAG_SERVICE_PRESET={path.as_posix()}\nRAG_CHUNK_SIZE=900")
    monkeypatch.setenv("CUSTOM_KEY", "custom-secret")
    result = Settings(_env_file=dotenv)
    assert result.chunk_size == 900
    assert result.planner_api_key.get_secret_value() == "custom-secret"


@pytest.mark.parametrize("data", [
    {"schema_version": 2},
    {"settings": {"planner_api_key": "bad"}},
    {"settings": {"service_preset": "recursive.json"}},
    {"settings": {"unknown": 1}},
    {"secret_refs": {"chunk_size": "SECRET"}},
    {"settings": {"planner_base_url": "https://user:secret@host/v1?token=bad"}},
])
def test_reject_unsafe_presets(data):
    with pytest.raises(ValueError):
        validate_preset(data, Settings.model_fields)


def test_snapshot_redacts_url_credentials_and_hash_is_stable():
    settings = Settings(_env_file=None, planner_api_key="secret-marker",
                        planner_base_url="https://user:secret-marker@host/v1?token=secret-marker",
                        reranker_cloud_instruct="text secret-marker")
    snapshot = config_snapshot(settings)
    assert "secret-marker" not in json.dumps(snapshot)
    assert snapshot == config_snapshot(settings)
    with pytest.raises(ValueError):
        export_preset(settings)
    assert snapshot["config_hash"] != config_snapshot(
        settings.model_copy(update={"chunk_size": 1200}))["config_hash"]


def test_missing_reference_fails_without_echoing_preset_values(tmp_path):
    path = tmp_path / "preset.json"
    path.write_text(json.dumps({"secret_refs": {"planner_api_key": "NONEXISTENT_TEST_KEY_8732"}}))
    with pytest.raises(ValueError, match="Missing preset credential"):
        Settings(_env_file=None, service_preset=path)
