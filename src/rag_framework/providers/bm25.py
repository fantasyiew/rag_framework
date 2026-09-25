"""Dependency-free in-memory BM25 keyword index used by the default local runtime."""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from threading import RLock
from typing import Any

from rag_framework.contracts.providers import KeywordStore
from rag_framework.core.models import Chunk, RetrievedChunk

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff\u3040-\u30ffー]+")


def tokenize(text: str) -> list[str]:
    """Tokenize Latin words and add character/bigram tokens for CJK text."""
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(text.lower()):
        value = match.group(0)
        if value.isascii():
            tokens.append(value)
            continue
        tokens.extend(value)
        tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
    return tokens


class InMemoryBM25KeywordStore(KeywordStore):
    """BM25 index with stable chunk IDs and generic metadata filtering."""

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._chunks: dict[str, Chunk] = {}
        self._tokens: dict[str, list[str]] = {}
        self._lock = RLock()

    async def upsert(self, chunks: list[Chunk]) -> None:
        with self._lock:
            for chunk in chunks:
                self._chunks[chunk.id] = chunk
                self._tokens[chunk.id] = tokenize(chunk.content)

    async def search(
        self, query: str, *, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]:
        return await asyncio.to_thread(self._search_sync, query, top_k, filters)

    def _search_sync(
        self, query: str, top_k: int, filters: dict[str, object]
    ) -> list[RetrievedChunk]:
        query_terms = tokenize(query)
        if not query_terms:
            return []

        with self._lock:
            eligible = {
                chunk_id: tokens
                for chunk_id, tokens in self._tokens.items()
                if self._matches_filters(self._chunks[chunk_id].metadata, filters)
            }
            if not eligible:
                return []

            document_count = len(eligible)
            average_length = sum(len(tokens) for tokens in eligible.values()) / document_count
            document_frequency = {
                term: sum(term in set(tokens) for tokens in eligible.values())
                for term in set(query_terms)
            }

            scored: list[tuple[str, float]] = []
            for chunk_id, tokens in eligible.items():
                frequencies = Counter(tokens)
                score = sum(
                    self._term_score(
                        frequency=frequencies[term],
                        document_length=len(tokens),
                        average_length=average_length,
                        document_count=document_count,
                        document_frequency=document_frequency[term],
                    )
                    for term in query_terms
                    if frequencies[term]
                )
                if score > 0:
                    scored.append((chunk_id, score))

            scored.sort(key=lambda item: (-item[1], item[0]))
            return [
                RetrievedChunk(
                    chunk=self._chunks[chunk_id],
                    score=score,
                    source="keyword:memory",
                    rank=rank,
                    component_scores={"keyword": score, "memory_bm25": score},
                )
                for rank, (chunk_id, score) in enumerate(scored[:top_k], start=1)
            ]

    def _term_score(
        self,
        *,
        frequency: int,
        document_length: int,
        average_length: float,
        document_count: int,
        document_frequency: int,
    ) -> float:
        inverse_document_frequency = math.log(
            1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        normalization = frequency + self.k1 * (
            1 - self.b + self.b * document_length / max(average_length, 1.0)
        )
        return inverse_document_frequency * frequency * (self.k1 + 1) / normalization

    @staticmethod
    def _matches_filters(metadata: dict[str, Any], filters: dict[str, object]) -> bool:
        for key, expected in filters.items():
            actual = metadata.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$eq" in expected and actual != expected["$eq"]:
                    return False
            elif isinstance(actual, list):
                if expected not in actual:
                    return False
            elif actual != expected:
                return False
        return True
