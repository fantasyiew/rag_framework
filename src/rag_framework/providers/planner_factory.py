"""Configuration-driven query planner construction."""

from __future__ import annotations

from dataclasses import dataclass

from rag_framework.config import Settings
from rag_framework.contracts.providers import QueryPlanner, StructuredOutputLLM
from rag_framework.providers.fixed_planner import FixedQueryPlanner
from rag_framework.providers.langchain import LangChainStructuredOutputLLM
from rag_framework.providers.router import HeuristicQueryPlanner, LLMQueryPlanner


@dataclass(frozen=True, slots=True)
class QueryPlannerRuntime:
    planner: QueryPlanner
    configured_mode: str
    active_mode: str
    provider: str
    fallback_reason: str | None = None


def build_query_planner(
    config: Settings,
    *,
    structured_llm: StructuredOutputLLM | None = None,
) -> QueryPlannerRuntime:
    """Build a planner without making a network request during application startup."""

    if config.query_planner_mode == "disabled":
        return QueryPlannerRuntime(
            planner=FixedQueryPlanner(config.default_retrieval_strategy,
                                      config.default_top_k, config.default_retrieval_rerank),
            configured_mode="disabled", active_mode="disabled", provider="built_in",
        )
    heuristic = HeuristicQueryPlanner(default_top_k=config.default_top_k)
    if config.query_planner_mode == "heuristic":
        return QueryPlannerRuntime(
            planner=heuristic,
            configured_mode="heuristic",
            active_mode="heuristic",
            provider="built_in",
        )

    if structured_llm is not None:
        return _llm_runtime(config, structured_llm)

    if config.planner_api_key is None:
        reason = "Planner API key is not configured."
        if config.query_planner_mode == "llm":
            raise ValueError(reason)
        return QueryPlannerRuntime(
            planner=heuristic,
            configured_mode=config.query_planner_mode,
            active_mode="heuristic",
            provider="built_in",
            fallback_reason=reason,
        )

    try:
        from langchain_openai import ChatOpenAI

        options: dict[str, object] = {
            "model": config.planner_model,
            "api_key": config.planner_api_key.get_secret_value(),
            "temperature": config.planner_temperature,
            "timeout": config.planner_request_timeout,
            "max_retries": config.planner_max_retries,
        }
        if config.planner_base_url:
            options["base_url"] = config.planner_base_url
        llm = LangChainStructuredOutputLLM(ChatOpenAI(**options))
    except Exception as exc:
        reason = f"Planner provider initialization failed: {type(exc).__name__}."
        if config.query_planner_mode == "llm":
            raise RuntimeError(reason) from exc
        return QueryPlannerRuntime(
            planner=heuristic,
            configured_mode=config.query_planner_mode,
            active_mode="heuristic",
            provider="built_in",
            fallback_reason=reason,
        )
    return _llm_runtime(config, llm)


def _llm_runtime(config: Settings, llm: StructuredOutputLLM) -> QueryPlannerRuntime:
    fallback = HeuristicQueryPlanner(default_top_k=config.default_top_k)
    planner = LLMQueryPlanner(
        llm,
        fallback,
        minimum_confidence=config.planner_minimum_confidence,
        max_rewrites=config.planner_max_rewrites,
    )
    return QueryPlannerRuntime(
        planner=planner,
        configured_mode=config.query_planner_mode,
        active_mode="llm",
        provider="langchain_openai_compatible",
    )
