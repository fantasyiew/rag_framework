"""Local and cloud reranker providers with a shared result contract."""

from __future__ import annotations

import asyncio
import math
from threading import Lock
from typing import Any

import httpx

from rag_framework.config import Settings
from rag_framework.contracts.providers import Reranker
from rag_framework.core.models import RetrievedChunk


class CrossEncoderReranker(Reranker):
    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        batch_size: int = 16,
        local_files_only: bool = True,
        model: Any = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.local_files_only = local_files_only
        self._model = model
        self._lock = Lock()

    async def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not candidates:
            return []
        return await asyncio.to_thread(self._predict, query, candidates)

    def _predict(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        with self._lock:
            if self._model is None:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    self.model_name,
                    device=self.device,
                    local_files_only=self.local_files_only,
                    trust_remote_code=False,
                )
            scores = self._model.predict(
                [(query, item.chunk.content) for item in candidates],
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
        return _rank_with_scores(candidates, [float(value) for value in scores])


class CloudReranker(Reranker):
    """Calls DashScope or its compatible rerank endpoint over HTTP."""

    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        model_name: str,
        protocol: str = "dashscope",
        timeout: float = 30.0,
        instruct: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if protocol not in {"dashscope", "compatible"}:
            raise ValueError("Unsupported cloud rerank protocol")
        self.url = url
        self._api_key = api_key
        self.model_name = model_name
        self.protocol = protocol
        self.instruct = instruct
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not candidates:
            return []
        response = await self._client.post(
            self.url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=self._request_body(query, candidates),
        )
        response.raise_for_status()
        payload = response.json()
        container = payload if self.protocol == "compatible" else payload.get("output", payload)
        raw_results = container.get("results") if isinstance(container, dict) else None
        if not isinstance(raw_results, list):
            raise TypeError("Cloud reranker response does not contain results")

        scores: list[float | None] = [None] * len(candidates)
        for result in raw_results:
            if not isinstance(result, dict):
                raise TypeError("Cloud reranker returned an invalid result")
            index = result.get("index")
            score = result.get("relevance_score")
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(candidates):
                raise ValueError("Cloud reranker returned an invalid document index")
            if scores[index] is not None:
                raise ValueError("Cloud reranker returned a duplicate document index")
            if not isinstance(score, int | float) or isinstance(score, bool):
                raise TypeError("Cloud reranker returned an invalid score")
            scores[index] = float(score)
        if any(score is None for score in scores):
            raise ValueError("Cloud reranker did not return every candidate")
        return _rank_with_scores(candidates, [score for score in scores if score is not None])

    def _request_body(self, query: str, candidates: list[RetrievedChunk]) -> dict[str, Any]:
        documents = [item.chunk.content for item in candidates]
        if self.protocol == "compatible":
            body: dict[str, Any] = {
                "model": self.model_name,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
                "return_documents": False,
            }
            if self.instruct:
                body["instruct"] = self.instruct
            return body

        parameters: dict[str, Any] = {
            "top_n": len(documents),
            "return_documents": False,
        }
        if self.instruct:
            parameters["instruct"] = self.instruct
        return {
            "model": self.model_name,
            "input": {"query": query, "documents": documents},
            "parameters": parameters,
        }

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _rank_with_scores(
    candidates: list[RetrievedChunk], scores: list[float]
) -> list[RetrievedChunk]:
    if len(scores) != len(candidates):
        raise ValueError("Reranker score count does not match candidates")
    results = []
    for item, score in zip(candidates, scores, strict=True):
        if not math.isfinite(score):
            raise ValueError("Reranker returned a non-finite score")
        results.append(
            item.model_copy(
                update={
                    "score": score,
                    "component_scores": {**item.component_scores, "rerank": score},
                }
            )
        )
    results.sort(key=lambda item: (-item.score, item.chunk.id))
    return [item.model_copy(update={"rank": rank}) for rank, item in enumerate(results, 1)]


def build_reranker(config: Settings) -> Reranker | None:
    if config.reranker_mode == "disabled":
        return None

    api_key = config.reranker_cloud_api_key or config.planner_api_key
    cloud_ready = config.reranker_cloud_url is not None and api_key is not None
    if config.reranker_mode == "cloud" and not cloud_ready:
        raise ValueError("Cloud reranker requires RAG_RERANKER_CLOUD_URL and an API key")
    if config.reranker_mode == "cloud" or (config.reranker_mode == "auto" and cloud_ready):
        assert config.reranker_cloud_url is not None and api_key is not None
        return CloudReranker(
            url=config.reranker_cloud_url,
            api_key=api_key.get_secret_value(),
            model_name=config.reranker_cloud_model,
            protocol=config.reranker_cloud_protocol,
            timeout=config.reranker_cloud_timeout,
            instruct=config.reranker_cloud_instruct,
        )

    return CrossEncoderReranker(
        config.reranker_model,
        device=config.reranker_device,
        batch_size=config.reranker_batch_size,
        local_files_only=config.reranker_local_files_only,
    )
