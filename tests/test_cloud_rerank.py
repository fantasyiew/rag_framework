import json

import httpx
import pytest
from test_retrieval import make_result

from rag_framework.config import Settings
from rag_framework.providers.rerank import CloudReranker, build_reranker


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "payload"),
    [
        (
            "dashscope",
            {"output": {"results": [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.15},
            ]}},
        ),
        (
            "compatible",
            {"results": [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.15},
            ]},
        ),
    ],
)
async def test_cloud_reranker_supports_both_official_response_shapes(protocol, payload):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    reranker = CloudReranker(
        url="https://rerank.test/api",
        api_key="secret",
        model_name="qwen-rerank",
        protocol=protocol,
        client=client(handler),
    )
    results = await reranker.rerank("Tokyo Tower", [make_result("a"), make_result("b")])

    assert [result.chunk.id for result in results] == ["b", "a"]
    assert results[0].component_scores["rerank"] == 0.95
    assert calls[0].headers["authorization"] == "Bearer secret"
    body = json.loads(calls[0].content)
    if protocol == "dashscope":
        assert body["input"]["query"] == "Tokyo Tower"
        assert body["parameters"]["top_n"] == 2
    else:
        assert body["query"] == "Tokyo Tower"
        assert body["top_n"] == 2
    await reranker._client.aclose()


@pytest.mark.asyncio
async def test_cloud_reranker_rejects_partial_results():
    reranker = CloudReranker(
        url="https://rerank.test/api",
        api_key="secret",
        model_name="qwen-rerank",
        client=client(lambda request: httpx.Response(
            200, json={"output": {"results": [{"index": 0, "relevance_score": 0.8}]}},
        )),
    )
    with pytest.raises(ValueError, match="every candidate"):
        await reranker.rerank("query", [make_result("a"), make_result("b")])
    await reranker._client.aclose()


def settings(**values):
    return Settings(_env_file=None, **values)


def test_auto_mode_prefers_configured_cloud_and_reuses_planner_key():
    reranker = build_reranker(settings(
        reranker_mode="auto",
        reranker_cloud_url="https://rerank.test/api",
        reranker_cloud_api_key=None,
        planner_api_key="planner-key",
    ))
    assert isinstance(reranker, CloudReranker)


def test_cloud_mode_requires_url_and_key():
    with pytest.raises(ValueError, match="requires"):
        build_reranker(settings(
            reranker_mode="cloud",
            reranker_cloud_url=None,
            reranker_cloud_api_key=None,
            planner_api_key=None,
        ))


def test_cloud_defaults_match_dashscope_gte_endpoint():
    reranker = build_reranker(settings(
        reranker_mode="cloud",
        reranker_cloud_api_key="placeholder",
        planner_api_key=None,
    ))
    assert isinstance(reranker, CloudReranker)
    assert reranker.model_name == "gte-rerank-v2"
    assert reranker.url == (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
