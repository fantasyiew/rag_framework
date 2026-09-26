from rag_framework.contracts.providers import StructuredOutputLLM
from rag_framework.core.models import (
    Chunk,
    GeneratedAnswer,
    Query,
    RAGResponse,
    RetrievalTrace,
    RetrievedChunk,
)
from rag_framework.evaluation import EvaluationCase
from rag_framework.evaluation.judges import (
    HeuristicAnswerJudge,
    LLMAnswerJudge,
    ResilientAnswerJudge,
)


class StubJudgeLLM(StructuredOutputLLM):
    def __init__(self, payload: dict[str, object] | None = None, *, fail: bool = False) -> None:
        self.payload = payload or {}
        self.fail = fail
        self.system_prompt = ""
        self.user_prompt = ""

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        if self.fail:
            raise ConnectionError("judge unavailable")
        return self.payload


def _case_and_response(*, reference_answer: str | None = "Tokyo Tower is 333 meters tall."):
    result = RetrievedChunk(
        chunk=Chunk(
            id="relevant",
            document_id="doc-1",
            index=0,
            content="Tokyo Tower is 333 meters tall.",
        ),
        score=1.0,
        source="test",
        rank=1,
    )
    query = Query(text="How tall is Tokyo Tower?")
    trace = RetrievalTrace(query=query, candidates=[result], final_context=[result])
    trace.add_step("generate_answer", 1.0, context_count=1)
    case = EvaluationCase(
        query=query,
        relevant_chunk_ids=["relevant"],
        reference_answer=reference_answer,
    )
    response = RAGResponse(
        retrieval=trace,
        answer=GeneratedAnswer(
            text="Tokyo Tower is 333 meters tall [1].",
            model="test",
        ),
    )
    return case, response


async def test_llm_judge_merges_semantic_and_deterministic_metrics() -> None:
    llm = StubJudgeLLM(
        {
            "groundedness": 0.91,
            "answer_relevancy": 0.82,
            "citation_correctness": 0.73,
            "reference_similarity": 0.64,
            "rationale": "The answer is supported and directly addresses the question.",
        }
    )
    case, response = _case_and_response()

    metrics = await LLMAnswerJudge(llm).evaluate(case, response)

    assert metrics.method == "llm_judge_v1"
    assert metrics.groundedness == 0.91
    assert metrics.answer_relevancy == 0.82
    assert metrics.citation_correctness == 0.73
    assert metrics.reference_similarity == 0.64
    assert metrics.citation_validity == 1
    assert metrics.citation_precision == 1
    assert metrics.citation_recall == 1
    assert metrics.judge_rationale is not None
    assert "untrusted" in llm.system_prompt
    assert "Tokyo Tower" in llm.user_prompt


async def test_llm_judge_ignores_reference_score_without_reference_answer() -> None:
    llm = StubJudgeLLM(
        {
            "groundedness": 1,
            "answer_relevancy": 1,
            "citation_correctness": 1,
            "reference_similarity": 1,
            "rationale": "Supported.",
        }
    )
    case, response = _case_and_response(reference_answer=None)

    metrics = await LLMAnswerJudge(llm).evaluate(case, response)

    assert metrics.reference_similarity is None


async def test_resilient_judge_falls_back_without_leaking_provider_error() -> None:
    case, response = _case_and_response()
    judge = ResilientAnswerJudge(
        LLMAnswerJudge(StubJudgeLLM(fail=True)),
        HeuristicAnswerJudge(),
    )

    metrics = await judge.evaluate(case, response)

    assert metrics.method == "heuristic_v1"
    assert metrics.fallback_used is True
    assert metrics.fallback_reason == "ConnectionError"
    assert "unavailable" not in metrics.fallback_reason
