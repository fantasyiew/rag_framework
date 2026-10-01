"""Grounded answer generation over observable retrieval results."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from time import perf_counter

from rag_framework.contracts.providers import AnswerGenerator, Retriever
from rag_framework.core.models import (
    Citation,
    GeneratedAnswer,
    Query,
    RAGResponse,
    RAGStreamEvent,
    RetrievalTrace,
    RetrievedChunk,
)

_CITATION_PATTERN = re.compile(r"\[(\d+)]")


class GenerationPipeline:
    def __init__(
        self,
        retriever: Retriever,
        generator: AnswerGenerator,
        *,
        max_context_chunks: int = 8,
    ) -> None:
        if max_context_chunks < 1:
            raise ValueError("max_context_chunks must be at least 1")
        self.retriever = retriever
        self.generator = generator
        self.max_context_chunks = max_context_chunks

    async def run(self, query: Query) -> RAGResponse:
        trace = await self.retriever.retrieve(query)
        contexts = trace.final_context[: self.max_context_chunks]
        started = perf_counter()
        text = await self.generator.generate(query, contexts)
        answer = self._answer(text, contexts)
        self._record_generation(trace, started, contexts, answer)
        return RAGResponse(retrieval=trace, answer=answer)

    async def stream(self, query: Query) -> AsyncIterator[RAGStreamEvent]:
        trace = await self.retriever.retrieve(query)
        contexts = trace.final_context[: self.max_context_chunks]
        yield RAGStreamEvent(
            type="retrieval",
            data={"trace": trace.model_dump(mode="json"), "context_count": len(contexts)},
        )

        started = perf_counter()
        tokens = []
        async for token in self.generator.stream(query, contexts):
            tokens.append(token)
            yield RAGStreamEvent(type="token", data={"text": token})

        answer = self._answer("".join(tokens), contexts)
        self._record_generation(trace, started, contexts, answer)
        yield RAGStreamEvent(
            type="complete",
            data={
                "answer": answer.model_dump(mode="json"),
                "trace": trace.model_dump(mode="json"),
            },
        )

    def _answer(self, text: str, contexts: list[RetrievedChunk]) -> GeneratedAnswer:
        citation_numbers = sorted(
            {
                int(match)
                for match in _CITATION_PATTERN.findall(text)
                if 1 <= int(match) <= len(contexts)
            }
        )
        citations = [self._citation(number, contexts[number - 1]) for number in citation_numbers]
        return GeneratedAnswer(
            text=text,
            citations=citations,
            model=self.generator.model_name,
            fallback_used=self.generator.fallback_used,
        )

    def _record_generation(
        self,
        trace: RetrievalTrace,
        started: float,
        contexts: list[RetrievedChunk],
        answer: GeneratedAnswer,
    ) -> None:
        trace.add_step(
            "generate_answer",
            (perf_counter() - started) * 1000,
            model=self.generator.model_name,
            fallback_used=self.generator.fallback_used,
            context_count=len(contexts),
            citation_count=len(answer.citations),
            output_characters=len(answer.text),
            prompt_hash=getattr(getattr(self.generator, 'primary', self.generator), 'prompt_hash', None),
            context_chunk_ids=[item.chunk.id for item in contexts],
        )

    @staticmethod
    def _citation(number: int, result: RetrievedChunk) -> Citation:
        preview = " ".join(result.chunk.content.split())[:240]
        return Citation(
            number=number,
            chunk_id=result.chunk.id,
            document_id=result.chunk.document_id,
            source_uri=result.chunk.source_uri,
            content_preview=preview,
        )
