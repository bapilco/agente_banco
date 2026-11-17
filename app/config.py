"""Configuración de la aplicación, leída desde variables de entorno / archivo .env."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Proveedor de LLM
    llm_provider: Literal["ollama", "bedrock"] = "ollama"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:1.7b"

    # AWS Bedrock
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-haiku-5-5"

    # Orquestador
    agent_max_retries: int = 3
    agent_timeout_seconds: float = 60.0
    agent_retry_backoff_seconds: float = 0.5
    identity_confidence_threshold: float = 0.8

    # Mocks
    mock_failure_rate: float = 0.0

    @property
    def llm_model_name(self) -> str:
        return self.ollama_model if self.llm_provider == "ollama" else self.bedrock_model_id


@lru_cache
def get_settings() -> Settings:
    return Settings()
