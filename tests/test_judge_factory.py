import pytest

from rag_framework.config import Settings
from rag_framework.contracts.providers import StructuredOutputLLM
from rag_framework.evaluation.judges import (
    HeuristicAnswerJudge,
    LLMAnswerJudge,
    ResilientAnswerJudge,
)
from rag_framework.providers.judge_factory import build_answer_judge


class StubLLM(StructuredOutputLLM):
    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        return {}


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def test_heuristic_judge_is_default() -> None:
    runtime = build_answer_judge(settings())

    assert isinstance(runtime.judge, HeuristicAnswerJudge)
    assert runtime.active_mode == "heuristic"


def test_auto_judge_uses_heuristic_without_credentials() -> None:
    runtime = build_answer_judge(
        settings(
            evaluation_judge_mode="auto",
            evaluation_judge_api_key=None,
            generation_api_key=None,
            planner_api_key=None,
        )
    )

    assert isinstance(runtime.judge, HeuristicAnswerJudge)
    assert runtime.fallback_reason == "Evaluation judge API key is not configured."


def test_llm_judge_requires_credentials() -> None:
    with pytest.raises(ValueError, match="API key"):
        build_answer_judge(
            settings(
                evaluation_judge_mode="llm",
                evaluation_judge_api_key=None,
                generation_api_key=None,
                planner_api_key=None,
            )
        )


def test_injected_llm_builds_strict_and_resilient_judges() -> None:
    strict = build_answer_judge(
        settings(evaluation_judge_mode="llm"),
        structured_llm=StubLLM(),
    )
    resilient = build_answer_judge(
        settings(evaluation_judge_mode="auto"),
        structured_llm=StubLLM(),
    )

    assert isinstance(strict.judge, LLMAnswerJudge)
    assert isinstance(resilient.judge, ResilientAnswerJudge)
    assert resilient.active_mode == "llm"


def test_openai_compatible_judge_initializes_without_network_request() -> None:
    pytest.importorskip("langchain_openai")

    runtime = build_answer_judge(
        settings(
            evaluation_judge_mode="llm",
            evaluation_judge_api_key="test-key",
            evaluation_judge_model="test-model",
            evaluation_judge_base_url="http://localhost:9999/v1",
        )
    )

    assert isinstance(runtime.judge, LLMAnswerJudge)
    assert runtime.model == "test-model"
