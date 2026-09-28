"""Trusted in-process algorithm registration; unknown modes fail explicitly."""

from collections.abc import Callable
from typing import Generic, TypeVar

from rag_framework.config import Settings
from rag_framework.contracts.providers import Chunker, Fusion
from rag_framework.pipeline.fusion import RRFFusion
from rag_framework.pipeline.indexing import CharacterChunker

T = TypeVar("T")


class AlgorithmRegistry(Generic[T]):
    def __init__(self, contract: type[T]):
        self.contract = contract
        self.factories: dict[str, Callable[[Settings], T]] = {}

    def register(self, name: str, factory: Callable[[Settings], T]):
        if not name.strip() or name in self.factories:
            raise ValueError(f"Empty or duplicate algorithm name: {name}")
        self.factories[name] = factory

    def build(self, name: str, settings: Settings) -> T:
        if name not in self.factories:
            raise ValueError(f"Unknown {self.contract.__name__} mode: {name}")
        instance = self.factories[name](settings)
        if not isinstance(instance, self.contract):
            raise TypeError(f"{name} must implement {self.contract.__name__}")
        return instance


chunkers = AlgorithmRegistry(Chunker)
fusions = AlgorithmRegistry(Fusion)
chunkers.register("character", lambda s: CharacterChunker(s.chunk_size, s.chunk_overlap))
fusions.register("rrf", lambda s: RRFFusion(s.effective_fusion_rank_constant))


def build_chunker(settings: Settings) -> Chunker:
    return chunkers.build(settings.chunker_mode, settings)


def build_fusion(settings: Settings) -> Fusion:
    return fusions.build(settings.fusion_mode, settings)
