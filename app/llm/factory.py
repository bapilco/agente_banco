"""Fábrica del modelo de chat. Ningún agente conoce el proveedor concreto."""

from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings


@lru_cache
def get_chat_model() -> BaseChatModel:
    settings = get_settings()

    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0,
            reasoning=False,  # qwen3: desactiva el modo "thinking" para respuestas más rápidas
            client_kwargs={"timeout": settings.agent_timeout_seconds},
        )

    if settings.llm_provider == "bedrock":
        from botocore.config import Config
        from langchain_aws import ChatBedrockConverse

        # Claude Haiku 5.5 no acepta valores no predeterminados de temperature/top_p,
        # por eso no se envían parámetros de muestreo.
        return ChatBedrockConverse(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
            max_tokens=1024,
            config=Config(read_timeout=settings.agent_timeout_seconds, retries={"max_attempts": 1}),
        )

    raise ValueError(f"LLM_PROVIDER no soportado: {settings.llm_provider}")
