"""Configuration-driven answer generator construction."""

from __future__ import annotations

from dataclasses import dataclass

from rag_framework.config import Settings
from rag_framework.contracts.providers import AnswerGenerator
from rag_framework.providers.generation import (
    ExtractiveAnswerGenerator,
    LangChainAnswerGenerator,
    ResilientAnswerGenerator,
)


@dataclass(frozen=True, slots=True)
class AnswerGeneratorRuntime:
    generator: AnswerGenerator
    configured_mode: str
    active_mode: str
    provider: str
    model: str
    fallback_reason: str | None = None


def build_answer_generator(config: Settings) -> AnswerGeneratorRuntime:
    extractive = ExtractiveAnswerGenerator()
    if config.answer_generator_mode == "extractive":
        fallback = ExtractiveAnswerGenerator(fallback_used=True)
        return AnswerGeneratorRuntime(
            generator=fallback,
            configured_mode="extractive",
            active_mode="extractive",
            provider="built_in",
            model=fallback.model_name,
        )

    api_key = config.generation_api_key or config.planner_api_key
    model = config.generation_model or config.planner_model
    base_url = config.generation_base_url or config.planner_base_url
    if api_key is None:
        reason = "Generation API key is not configured."
        if config.answer_generator_mode == "llm":
            raise ValueError(reason)
        fallback = ExtractiveAnswerGenerator(fallback_used=True)
        return AnswerGeneratorRuntime(
            generator=fallback,
            configured_mode=config.answer_generator_mode,
            active_mode="extractive",
            provider="built_in",
            model=fallback.model_name,
            fallback_reason=reason,
        )

    try:
        from langchain_openai import ChatOpenAI

        options: dict[str, object] = {
            "model": model,
            "api_key": api_key.get_secret_value(),
            "temperature": config.generation_temperature,
            "timeout": config.generation_request_timeout,
            "max_retries": config.generation_max_retries,
            "max_tokens": config.generation_max_tokens,
        }
        if base_url:
            options["base_url"] = base_url
        generator = LangChainAnswerGenerator(ChatOpenAI(**options), model_name=model)
    except Exception as exc:
        reason = f"Answer provider initialization failed: {type(exc).__name__}."
        if config.answer_generator_mode == "llm":
            raise RuntimeError(reason) from exc
        return AnswerGeneratorRuntime(
            generator=extractive,
            configured_mode=config.answer_generator_mode,
            active_mode="extractive",
            provider="built_in",
            model=extractive.model_name,
            fallback_reason=reason,
        )
    active_generator: AnswerGenerator = generator
    if config.answer_generator_mode == "auto":
        active_generator = ResilientAnswerGenerator(
            generator,
            ExtractiveAnswerGenerator(fallback_used=True),
        )
    return AnswerGeneratorRuntime(
        generator=active_generator,
        configured_mode=config.answer_generator_mode,
        active_mode="llm",
        provider="langchain_openai_compatible",
        model=model,
    )
