"""Provider resilience wrappers."""

from __future__ import annotations

import logging

from rag_framework.contracts.providers import KeywordStore
from rag_framework.core.models import Chunk, RetrievedChunk

logger = logging.getLogger(__name__)


class ResilientKeywordStore(KeywordStore):
    """Mirror writes to memory and use it when the primary keyword store fails."""

    def __init__(self, primary: KeywordStore, fallback: KeywordStore) -> None:
        self.primary = primary
        self.fallback = fallback

    async def upsert(self, chunks: list[Chunk]) -> None:
        await self.fallback.upsert(chunks)
        try:
            await self.primary.upsert(chunks)
        except Exception:
            logger.exception("Primary keyword index failed; in-memory fallback remains available")

    async def search(
        self, query: str, *, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]:
        try:
            return await self.primary.search(query, top_k=top_k, filters=filters)
        except Exception:
            logger.exception("Primary keyword search failed; using in-memory fallback")
            results = await self.fallback.search(query, top_k=top_k, filters=filters)
            return [
                result.model_copy(update={"source": "keyword:memory:fallback"})
                for result in results
            ]

    async def health(self) -> bool:
        health = getattr(self.primary, "health", None)
        return bool(await health()) if health is not None else True

    async def close(self) -> None:
        close = getattr(self.primary, "close", None)
        if close is not None:
            await close()
