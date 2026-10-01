"""Composición de dependencias (inyección simple, sin framework).

Se construye una única vez al iniciar la app. Para pruebas se puede crear un
`Container` con implementaciones alternativas.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.agent.agent import Agent
from app.config import Settings
from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.rag.embeddings import build_embedder
from app.rag.knowledge_base import KnowledgeBase
from app.rag.vectorstore import build_vector_store
from app.storage.history import HistoryStore, build_history_store
from app.storage.requests_repo import JsonRequestRepository

log = get_logger(__name__)


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "azure":
        from app.llm.azure_openai import AzureOpenAILLM

        return AzureOpenAILLM(settings)
    from app.llm.local import LocalLLM

    return LocalLLM()


@dataclass
class Container:
    settings: Settings
    kb: KnowledgeBase
    history: HistoryStore
    agent: Agent

    @classmethod
    def build(cls, settings: Settings) -> Container:
        kb = KnowledgeBase(settings, build_embedder(settings), build_vector_store(settings))
        history = build_history_store(settings)
        catalog_path = Path(settings.cloud_catalog_path)
        catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else []
        agent = Agent(settings, build_llm(settings), kb, JsonRequestRepository(settings.requests_db_path), catalog, history)
        log.info("container_built", extra={
            "llm": settings.llm_provider, "vector_store": settings.vector_store_provider,
            "history": settings.history_provider, "embedder": kb.embedder.name,
        })
        return cls(settings=settings, kb=kb, history=history, agent=agent)
