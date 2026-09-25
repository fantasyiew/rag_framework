from collections.abc import AsyncIterator

import pytest

from rag_framework.contracts.providers import AnswerGenerator, Retriever
from rag_framework.core.models import Chunk, Query, RetrievalTrace, RetrievedChunk
from rag_framework.pipeline.generation import GenerationPipeline
from rag_framework.providers.generation import ExtractiveAnswerGenerator, ResilientAnswerGenerator


class StubRetriever(Retriever):
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results

    async def retrieve(self, query: Query) -> RetrievalTrace:
        return RetrievalTrace(query=query, candidates=self.results, final_context=self.results)


class StubGenerator(AnswerGenerator):
    @property
    def model_name(self) -> str:
        return "stub-model"

    async def generate(self, query: Query, contexts: list[RetrievedChunk]) -> str:
        return "Tokyo Tower is 333 meters tall [1]. Invalid citation [9]."

    async def stream(
        self, query: Query, contexts: list[RetrievedChunk]
    ) -> AsyncIterator[str]:
        for token in ["Tokyo Tower ", "is 333 meters tall [1]."]:
            yield token


class FailingGenerator(AnswerGenerator):
    @property
    def model_name(self) -> str:
        return "failing-model"

    async def generate(self, query: Query, contexts: list[RetrievedChunk]) -> str:
        raise ConnectionError("provider unavailable")

    async def stream(
        self, query: Query, contexts: list[RetrievedChunk]
    ) -> AsyncIterator[str]:
        if False:
            yield ""
        raise ConnectionError("provider unavailable")


def result() -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id="chunk-1",
            document_id="doc-1",
            index=0,
            content="Tokyo Tower is 333 meters tall.",
            source_uri="https://example.test/tokyo-tower",
        ),
        score=0.9,
        source="vector",
        rank=1,
    )


@pytest.mark.asyncio
async def test_generation_pipeline_resolves_valid_citations_and_records_trace() -> None:
    pipeline = GenerationPipeline(StubRetriever([result()]), StubGenerator())

    response = await pipeline.run(Query(text="How tall is Tokyo Tower?"))

    assert response.answer.model == "stub-model"
    assert [citation.number for citation in response.answer.citations] == [1]
    assert response.answer.citations[0].chunk_id == "chunk-1"
    assert response.retrieval.steps[-1].name == "generate_answer"
    assert response.retrieval.steps[-1].details["citation_count"] == 1


@pytest.mark.asyncio
async def test_generation_pipeline_streams_retrieval_tokens_and_completion() -> None:
    pipeline = GenerationPipeline(StubRetriever([result()]), StubGenerator())

    events = [event async for event in pipeline.stream(Query(text="How tall is Tokyo Tower?"))]

    assert [event.type for event in events] == ["retrieval", "token", "token", "complete"]
    assert events[-1].data["answer"]["citations"][0]["document_id"] == "doc-1"
    assert events[-1].data["trace"]["steps"][-1]["name"] == "generate_answer"


@pytest.mark.asyncio
async def test_auto_generator_falls_back_to_extractive_answer() -> None:
    generator = ResilientAnswerGenerator(
        FailingGenerator(),
        ExtractiveAnswerGenerator(fallback_used=True),
    )
    pipeline = GenerationPipeline(StubRetriever([result()]), generator)

    response = await pipeline.run(Query(text="How tall is Tokyo Tower?"))

    assert response.answer.model == "extractive"
    assert response.answer.fallback_used is True
    assert response.answer.citations[0].number == 1
