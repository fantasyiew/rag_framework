"""Explicit, optional administrative capabilities for managed providers."""

from typing import Protocol, runtime_checkable

from rag_framework.core.models import Chunk, Document


@runtime_checkable
class StrictIndexWriter(Protocol):
    async def upsert_strict(self, chunks: list[Chunk]) -> None: ...


@runtime_checkable
class ChunkSnapshot(Protocol):
    def snapshot_chunks(self) -> list[Chunk]: ...


@runtime_checkable
class RecoverableIndex(Protocol):
    async def check_index(self) -> None: ...
    def canonical_documents(self) -> list[Document]: ...
    async def rebuild_documents(self, documents: list[Document]): ...
    async def clear_index(self) -> tuple[int, int]: ...


@runtime_checkable
class IndexAdmin(Protocol):
    async def count(self) -> int: ...
    async def clear(self) -> int: ...


@runtime_checkable
class HealthCheck(Protocol):
    async def health(self) -> bool: ...


@runtime_checkable
class AsyncClosable(Protocol):
    async def close(self) -> None: ...
