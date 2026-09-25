import pytest

from rag_framework.config import Settings
from rag_framework.providers.generation import (
    ExtractiveAnswerGenerator,
    LangChainAnswerGenerator,
    ResilientAnswerGenerator,
)
from rag_framework.providers.generation_factory import build_answer_generator


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def test_auto_generation_uses_extractive_fallback_without_credentials() -> None:
    runtime = build_answer_generator(
        settings(answer_generator_mode="auto", planner_api_key=None, generation_api_key=None)
    )

    assert isinstance(runtime.generator, ExtractiveAnswerGenerator)
    assert runtime.active_mode == "extractive"
    assert runtime.fallback_reason == "Generation API key is not configured."


def test_llm_generation_requires_credentials() -> None:
    with pytest.raises(ValueError, match="API key"):
        build_answer_generator(
            settings(answer_generator_mode="llm", planner_api_key=None, generation_api_key=None)
        )


def test_generation_reuses_planner_provider_settings_without_network_request() -> None:
    pytest.importorskip("langchain_openai")
    runtime = build_answer_generator(
        settings(
            answer_generator_mode="auto",
            planner_api_key="test-key",
            planner_model="test-model",
            planner_base_url="http://localhost:9999/v1",
        )
    )

    assert isinstance(runtime.generator, ResilientAnswerGenerator)
    assert isinstance(runtime.generator.primary, LangChainAnswerGenerator)
    assert runtime.active_mode == "llm"
    assert runtime.model == "test-model"
