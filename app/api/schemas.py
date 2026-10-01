"""Contratos de la API (request/response)."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000, examples=["¿Cuál es el SLA de resolución de una solicitud P2?"])
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{6,64}$",
                                   description="Permite conversación multi-turno. Si se omite se crea una nueva sesión.")

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("la pregunta no puede estar vacía")
        return v


class FeedbackRequest(BaseModel):
    interaction_id: str = Field(min_length=1, max_length=64)
    rating: str = Field(pattern=r"^(up|down)$", description="'up' (👍) o 'down' (👎)")
    comment: str | None = Field(default=None, max_length=500)


class Source(BaseModel):
    ref: int
    source: str
    section: str
    page: int | None = None
    score: float
    snippet: str
    cited: bool


class ToolCallTrace(BaseModel):
    name: str
    arguments: dict
    ok: bool
    elapsed_ms: int


class Grounding(BaseModel):
    score: float
    grounded: bool
    evaluated_sentences: int
    unsupported_sentences: list[str]
    invalid_citations: list[int]


class ChatResponse(BaseModel):
    interaction_id: str
    session_id: str
    answer: str
    status: str = Field(description="answered | no_info | blocked | output_blocked | incomplete")
    sources: list[Source]
    tool_calls: list[ToolCallTrace]
    grounding: Grounding | None
    security: dict
    usage: dict
    model: str
    prompt_version: str
    latency_ms: int


class IngestionResult(BaseModel):
    source: str
    chunks: int
    replaced_chunks: int
    flagged_chunks: int
    embedding_model: str
    elapsed_ms: int


class IngestionResponse(BaseModel):
    ingested: list[IngestionResult]
    errors: list[dict] = []
    total_chunks_in_index: int


class DocumentInfo(BaseModel):
    source: str
    chunks: int


class HistoryPage(BaseModel):
    items: list[dict]
    count: int
