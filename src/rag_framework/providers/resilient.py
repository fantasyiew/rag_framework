"""Provider resilience wrappers."""

from __future__ import annotations

import logging

from rag_framework.contracts.lifecycle import AsyncClosable, HealthCheck, IndexAdmin
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

    async def upsert_strict(self, chunks: list[Chunk]) -> None:
        # Managed writes must not mark a durable index ready after a primary failure.
        await self.primary.upsert(chunks)
        await self.fallback.upsert(chunks)

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
        return bool(await self.primary.health()) if isinstance(self.primary, HealthCheck) else True

    async def clear(self) -> int:
        fallback_count = await self.fallback.clear()
        primary_count = await self.primary.clear()
        return max(fallback_count, primary_count)

    async def count(self) -> int:
        if not isinstance(self.primary, IndexAdmin):
            raise TypeError("Primary store does not support index administration")
        return int(await self.primary.count())

    async def close(self) -> None:
        for store in (self.primary, self.fallback):
            if isinstance(store, AsyncClosable):
                await store.close()
