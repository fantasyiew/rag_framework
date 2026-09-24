"""LangChain adapters. They keep the framework core independent of LangChain types."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.documents import Document as LangChainDocument
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from rag_framework.contracts.providers import Embedder, StructuredOutputLLM
from rag_framework.core.models import Document, RetrievalPlan


class LangChainEmbedder(Embedder):
    """Adapts any LangChain Embeddings implementation to the framework port."""

    def __init__(self, embeddings: Embeddings) -> None:
        self.embeddings = embeddings

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._async_or_threaded("aembed_documents", "embed_documents", texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._async_or_threaded("aembed_query", "embed_query", text)

    async def _async_or_threaded(self, async_name: str, sync_name: str, value: Any) -> Any:
        async_method = getattr(self.embeddings, async_name, None)
        if async_method is not None:
            return await async_method(value)
        return await asyncio.to_thread(getattr(self.embeddings, sync_name), value)


class LangChainDocumentAdapter:
    """Converts documents at the boundary without leaking LangChain's model inward."""

    @staticmethod
    def to_core(document: LangChainDocument, *, source_uri: str | None = None) -> Document:
        metadata = dict(document.metadata)
        payload: dict[str, Any] = {
            "content": document.page_content,
            "source_uri": source_uri or metadata.pop("source", None),
            "metadata": metadata,
        }
        if document.id is not None:
            payload["id"] = str(document.id)
        return Document(**payload)

    @staticmethod
    def to_langchain(document: Document) -> LangChainDocument:
        return LangChainDocument(
            id=document.id,
            page_content=document.content,
            metadata={**document.metadata, "source": document.source_uri or ""},
        )


class LangChainStructuredOutputLLM(StructuredOutputLLM):
    """Uses a LangChain chat model's provider-native structured-output facility."""

    def __init__(self, chat_model: BaseChatModel) -> None:
        self._planner = chat_model.with_structured_output(RetrievalPlan)

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        result = await self._planner.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        if isinstance(result, RetrievalPlan):
            return result.model_dump()
        if isinstance(result, dict):
            return result
        raise TypeError("Structured LangChain model returned an unsupported result")
