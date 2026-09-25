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
