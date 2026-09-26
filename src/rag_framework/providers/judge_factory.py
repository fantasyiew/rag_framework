"""Configuration-driven answer judge construction."""

from __future__ import annotations

from dataclasses import dataclass

from rag_framework.config import Settings
from rag_framework.contracts.providers import StructuredOutputLLM
from rag_framework.evaluation.judges import (
    AnswerJudge,
    HeuristicAnswerJudge,
    LLMAnswerJudge,
    LLMJudgeScores,
    ResilientAnswerJudge,
)
from rag_framework.providers.langchain import LangChainStructuredOutputLLM


@dataclass(frozen=True, slots=True)
class AnswerJudgeRuntime:
    judge: AnswerJudge
    configured_mode: str
    active_mode: str
    provider: str
    model: str | None = None
    fallback_reason: str | None = None


def build_answer_judge(
    config: Settings,
    *,
    structured_llm: StructuredOutputLLM | None = None,
) -> AnswerJudgeRuntime:
    heuristic = HeuristicAnswerJudge()
    if config.evaluation_judge_mode == "heuristic":
        return AnswerJudgeRuntime(
            judge=heuristic,
            configured_mode="heuristic",
            active_mode="heuristic",
            provider="built_in",
        )

    model = config.evaluation_judge_model or config.generation_model or config.planner_model
    if structured_llm is not None:
        return _llm_runtime(config, structured_llm, model)

    api_key = (
        config.evaluation_judge_api_key
        or config.generation_api_key
        or config.planner_api_key
    )
    base_url = (
        config.evaluation_judge_base_url
        or config.generation_base_url
        or config.planner_base_url
    )
    if api_key is None:
        reason = "Evaluation judge API key is not configured."
        if config.evaluation_judge_mode == "llm":
            raise ValueError(reason)
        return AnswerJudgeRuntime(
            judge=heuristic,
            configured_mode=config.evaluation_judge_mode,
            active_mode="heuristic",
            provider="built_in",
            fallback_reason=reason,
        )

    try:
        from langchain_openai import ChatOpenAI

        options: dict[str, object] = {
            "model": model,
            "api_key": api_key.get_secret_value(),
            "temperature": config.evaluation_judge_temperature,
            "timeout": config.evaluation_judge_request_timeout,
            "max_retries": config.evaluation_judge_max_retries,
            "max_tokens": config.evaluation_judge_max_tokens,
        }
        if base_url:
            options["base_url"] = base_url
        structured_llm = LangChainStructuredOutputLLM(
            ChatOpenAI(**options),
            schema=LLMJudgeScores,
        )
    except Exception as exc:
        reason = f"Evaluation judge provider initialization failed: {type(exc).__name__}."
        if config.evaluation_judge_mode == "llm":
            raise RuntimeError(reason) from exc
        return AnswerJudgeRuntime(
            judge=heuristic,
            configured_mode=config.evaluation_judge_mode,
            active_mode="heuristic",
            provider="built_in",
            fallback_reason=reason,
        )
    return _llm_runtime(config, structured_llm, model)


def _llm_runtime(
    config: Settings,
    structured_llm: StructuredOutputLLM,
    model: str,
) -> AnswerJudgeRuntime:
    judge: AnswerJudge = LLMAnswerJudge(
        structured_llm,
        max_context_characters=config.evaluation_judge_max_context_characters,
    )
    if config.evaluation_judge_mode == "auto":
        judge = ResilientAnswerJudge(judge, HeuristicAnswerJudge())
    return AnswerJudgeRuntime(
        judge=judge,
        configured_mode=config.evaluation_judge_mode,
        active_mode="llm",
        provider="langchain_openai_compatible",
        model=model,
    )
