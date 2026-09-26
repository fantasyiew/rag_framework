"""Runtime configuration; provider choices remain outside pipeline code."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RAG_", extra="ignore")

    chroma_directory: Path = Path("data/chroma")
    chroma_collection: str = "documents"
    embedding_dimensions: int = 384
    default_top_k: int = 8
    reranker_mode: Literal["disabled", "cross_encoder", "cloud", "auto"] = "disabled"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_device: str = "cpu"
    reranker_batch_size: int = Field(default=16, ge=1)
    reranker_candidate_k: int = Field(default=32, ge=1, le=1000)
    reranker_local_files_only: bool = True
    reranker_cloud_protocol: Literal["dashscope", "compatible"] = "dashscope"
    reranker_cloud_model: str = "gte-rerank-v2"
    reranker_cloud_url: str | None = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    reranker_cloud_api_key: SecretStr | None = None
    reranker_cloud_timeout: float = Field(default=30.0, gt=0)
    reranker_cloud_instruct: str | None = None
    query_planner_mode: Literal["heuristic", "llm", "auto"] = "auto"
    planner_model: str = "gpt-4o-mini"
    planner_api_key: SecretStr | None = None
    planner_base_url: str | None = None
    planner_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    planner_request_timeout: float = Field(default=30.0, gt=0)
    planner_max_retries: int = Field(default=2, ge=0)
    planner_minimum_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    planner_max_rewrites: int = Field(default=4, ge=0, le=10)
    answer_generator_mode: Literal["extractive", "llm", "auto"] = "auto"
    generation_model: str | None = None
    generation_api_key: SecretStr | None = None
    generation_base_url: str | None = None
    generation_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    generation_request_timeout: float = Field(default=60.0, gt=0)
    generation_max_retries: int = Field(default=2, ge=0)
    generation_max_tokens: int = Field(default=1024, ge=1)
    generation_max_context_chunks: int = Field(default=8, ge=1, le=100)
    evaluation_concurrency: int = Field(default=4, ge=1, le=32)
    evaluation_report_limit: int = Field(default=100, ge=1, le=10000)
    evaluation_report_directory: Path = Path("data/evaluation/reports")
    evaluation_dataset_directory: Path = Path("data/evaluation/datasets")
    evaluation_dataset_max_cases: int = Field(default=10000, ge=1, le=100000)
    evaluation_dataset_max_bytes: int = Field(default=5_000_000, ge=1024)
    evaluation_judge_mode: Literal["heuristic", "llm", "auto"] = "heuristic"
    evaluation_judge_model: str | None = None
    evaluation_judge_api_key: SecretStr | None = None
    evaluation_judge_base_url: str | None = None
    evaluation_judge_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    evaluation_judge_request_timeout: float = Field(default=60.0, gt=0)
    evaluation_judge_max_retries: int = Field(default=2, ge=0)
    evaluation_judge_max_tokens: int = Field(default=1024, ge=1)
    evaluation_judge_max_context_characters: int = Field(default=12000, ge=1)
    hybrid_candidate_multiplier: int = Field(default=2, ge=1)
    rrf_rank_constant: int = Field(default=60, ge=0)
    keyword_backend: Literal["memory", "elasticsearch"] = "memory"
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "rag_chunks"
    elasticsearch_api_key: SecretStr | None = None
    elasticsearch_username: str | None = None
    elasticsearch_password: SecretStr | None = None
    elasticsearch_verify_certs: bool = True
    elasticsearch_request_timeout: float = Field(default=10.0, gt=0)
    elasticsearch_analyzer: str = "standard"
    elasticsearch_bm25_k1: float = Field(default=1.2, gt=0)
    elasticsearch_bm25_b: float = Field(default=0.75, ge=0, le=1)


settings = Settings()
