"""Runtime configuration; provider choices remain outside pipeline code."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RAG_", extra="ignore")

    chroma_directory: Path = Path("data/chroma")
    chroma_collection: str = "documents"
    embedding_dimensions: int = 384
    default_top_k: int = 8


settings = Settings()
