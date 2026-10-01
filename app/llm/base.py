"""Contrato común de los clientes LLM (puerto)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


class LLMClient(Protocol):
    model_name: str

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse: ...
