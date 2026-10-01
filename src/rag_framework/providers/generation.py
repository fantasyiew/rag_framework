"""Answer generators backed by LangChain chat models or deterministic extraction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from rag_framework.contracts.providers import AnswerGenerator
from rag_framework.core.models import Query, RetrievedChunk
from rag_framework.prompts import SYSTEM_PROMPT, USER_PROMPT, validate_user_prompt


class LangChainAnswerGenerator(AnswerGenerator):
    _SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, chat_model: BaseChatModel, *, model_name: str,
                 system_prompt: str = SYSTEM_PROMPT, user_prompt: str = USER_PROMPT) -> None:
        self.chat_model = chat_model
        self._model_name = model_name
        self.system_prompt = system_prompt
        self.user_prompt = validate_user_prompt(user_prompt)
        self.prompt_hash = hashlib.sha256((system_prompt + '\0' + user_prompt).encode()).hexdigest()

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, query: Query, contexts: list[RetrievedChunk]) -> str:
        response = await self.chat_model.ainvoke(self._messages(query, contexts))
        return _content_to_text(response.content)

    async def stream(
        self, query: Query, contexts: list[RetrievedChunk]
    ) -> AsyncIterator[str]:
        async for chunk in self.chat_model.astream(self._messages(query, contexts)):
            text = _content_to_text(chunk.content)
            if text:
                yield text

    def _messages(
        self, query: Query, contexts: list[RetrievedChunk]
    ) -> list[SystemMessage | HumanMessage]:
        context_blocks = []
        for number, result in enumerate(contexts, 1):
            source = result.chunk.source_uri or result.chunk.document_id
            metadata = json.dumps(result.chunk.metadata, ensure_ascii=False, default=str)
            context_blocks.append(
                f"[{number}] source={source}; chunk_id={result.chunk.id}; metadata={metadata}\n"
                f"{result.chunk.content}"
            )
        context_text = "\n\n".join(context_blocks) or "(no relevant context retrieved)"
        history = "\n".join(query.history[-6:]) or "(none)"
        prompt = self.user_prompt.format(history=history, context=context_text, question=query.text)
        return [SystemMessage(content=self.system_prompt), HumanMessage(content=prompt)]


class ExtractiveAnswerGenerator(AnswerGenerator):
    """Safe no-LLM fallback that exposes retrieved evidence without synthesis."""

    def __init__(self, *, fallback_used: bool = False) -> None:
        self._fallback_used = fallback_used

    @property
    def model_name(self) -> str:
        return "extractive"

    @property
    def fallback_used(self) -> bool:
        return self._fallback_used

    async def generate(self, query: Query, contexts: list[RetrievedChunk]) -> str:
        if not contexts:
            return "No relevant context was retrieved, so an answer cannot be generated."
        lines = ["Retrieved evidence:"]
        lines.extend(f"- {item.chunk.content.strip()} [{index}]" for index, item in enumerate(contexts, 1))
        return "\n".join(lines)

    async def stream(
        self, query: Query, contexts: list[RetrievedChunk]
    ) -> AsyncIterator[str]:
        yield await self.generate(query, contexts)


class ResilientAnswerGenerator(AnswerGenerator):
    """Falls back before output starts while keeping concurrent request state isolated."""

    def __init__(self, primary: AnswerGenerator, fallback: AnswerGenerator) -> None:
        self.primary = primary
        self.fallback = fallback
        self._used_fallback: ContextVar[bool] = ContextVar("generation_fallback", default=False)

    @property
    def model_name(self) -> str:
        return self.fallback.model_name if self._used_fallback.get() else self.primary.model_name

    @property
    def fallback_used(self) -> bool:
        return self._used_fallback.get()

    async def generate(self, query: Query, contexts: list[RetrievedChunk]) -> str:
        self._used_fallback.set(False)
        try:
            return await self.primary.generate(query, contexts)
        except Exception:  # noqa: BLE001 - Auto mode promises a safe generation fallback.
            self._used_fallback.set(True)
            return await self.fallback.generate(query, contexts)

    async def stream(
        self, query: Query, contexts: list[RetrievedChunk]
    ) -> AsyncIterator[str]:
        self._used_fallback.set(False)
        emitted = False
        try:
            async for token in self.primary.stream(query, contexts):
                emitted = True
                yield token
        except Exception:
            if emitted:
                raise
            self._used_fallback.set(True)
            async for token in self.fallback.stream(query, contexts):
                yield token


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(getattr(item, "text", None), str):
                parts.append(item.text)
        return "".join(parts)
    return str(content) if content is not None else ""
