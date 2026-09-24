"""Deterministic dependency-free embedder for local development and contract tests."""

from __future__ import annotations

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

from rag_framework.providers.langchain import LangChainEmbedder


class HashEmbeddings(Embeddings):
    """LangChain-compatible deterministic embeddings for local development."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"\w+", text.lower()):
            bucket = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dimensions
            vector[bucket] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]


class HashEmbedder(LangChainEmbedder):
    """Framework embedder backed by the LangChain Embeddings interface."""

    def __init__(self, dimensions: int = 384) -> None:
        super().__init__(HashEmbeddings(dimensions))
