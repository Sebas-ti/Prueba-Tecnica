"""Cliente de Azure OpenAI (chat con function calling)."""
from __future__ import annotations

from app.config import Settings
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.llm.base import LLMResponse, ToolCall

log = get_logger(__name__)


def build_azure_openai_client(settings: Settings):
    """Crea el cliente. Sin API key usa Managed Identity / Entra ID (recomendado)."""
    from openai import AzureOpenAI

    common = dict(
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        max_retries=3,  # reintentos con backoff exponencial ante 429/5xx
        timeout=30.0,
    )
    if settings.azure_openai_api_key:
        return AzureOpenAI(api_key=settings.azure_openai_api_key.get_secret_value(), **common)
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(azure_ad_token_provider=token_provider, **common)


def is_reasoning_deployment(name: str) -> bool:
    n = name.lower()
    return n.startswith("gpt-5") or (len(n) > 1 and n[0] == "o" and n[1].isdigit())


class AzureOpenAILLM:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.client = client or build_azure_openai_client(settings)
        self.model_name = f"azure-openai:{settings.azure_openai_chat_deployment}"
        flag = settings.azure_openai_reasoning_model
        self.reasoning = is_reasoning_deployment(settings.azure_openai_chat_deployment) if flag is None else flag

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        kwargs: dict = dict(model=self.settings.azure_openai_chat_deployment, messages=messages)
        if self.reasoning:
            # Los modelos de razonamiento no aceptan temperature/max_tokens; el presupuesto
            # incluye los tokens de razonamiento, por eso es mayor.
            kwargs.update(max_completion_tokens=self.settings.llm_max_tokens * 4,
                          reasoning_effort=self.settings.reasoning_effort)
        else:
            kwargs.update(temperature=self.settings.llm_temperature, max_tokens=self.settings.llm_max_tokens)
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
            if not self.reasoning:
                kwargs["parallel_tool_calls"] = True
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            # El filtro de contenido de Azure devuelve 400 con code=content_filter
            code = getattr(exc, "code", None) or type(exc).__name__
            log.error("llm_call_failed", extra={"error": str(code)})
            raise UpstreamError("Fallo invocando Azure OpenAI", details={"code": str(code)}) from exc
        choice = resp.choices[0]
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "{}")
            for tc in (choice.message.tool_calls or [])
        ]
        usage = resp.usage
        return LLMResponse(
            content=choice.message.content,
            tool_calls=calls,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=self.model_name,
        )
