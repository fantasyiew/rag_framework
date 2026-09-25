import pytest

from rag_framework.config import Settings
from rag_framework.contracts.providers import StructuredOutputLLM
from rag_framework.providers.planner_factory import build_query_planner
from rag_framework.providers.router import HeuristicQueryPlanner, LLMQueryPlanner


class StubLLM(StructuredOutputLLM):
    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        return {}


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def test_auto_mode_uses_heuristic_without_api_key() -> None:
    runtime = build_query_planner(settings(query_planner_mode="auto", planner_api_key=None))

    assert isinstance(runtime.planner, HeuristicQueryPlanner)
    assert runtime.active_mode == "heuristic"
    assert runtime.fallback_reason == "Planner API key is not configured."


def test_llm_mode_requires_api_key_without_injected_provider() -> None:
    with pytest.raises(ValueError, match="API key"):
        build_query_planner(settings(query_planner_mode="llm", planner_api_key=None))


def test_injected_structured_llm_builds_llm_planner() -> None:
    runtime = build_query_planner(
        settings(query_planner_mode="auto", planner_api_key=None),
        structured_llm=StubLLM(),
    )

    assert isinstance(runtime.planner, LLMQueryPlanner)
    assert runtime.active_mode == "llm"
    assert runtime.provider == "langchain_openai_compatible"


def test_openai_compatible_provider_initializes_without_network_request() -> None:
    pytest.importorskip("langchain_openai")

    runtime = build_query_planner(
        settings(
            query_planner_mode="llm",
            planner_api_key="test-key",
            planner_model="test-model",
            planner_base_url="http://localhost:9999/v1",
        )
    )

    assert isinstance(runtime.planner, LLMQueryPlanner)
    assert runtime.active_mode == "llm"
