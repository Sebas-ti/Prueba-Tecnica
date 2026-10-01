"""Generación de embeddings.

- `AzureOpenAIEmbedder`: text-embedding-3-small en Azure OpenAI. Autenticación
  con API key o, preferiblemente, Managed Identity (Entra ID).
- `HashingEmbedder`: alternativa local, determinista y sin dependencias de red
  (hashing de unigramas, bigramas y trigramas de caracteres). Permite ejecutar
  la solución completa y las pruebas sin credenciales; no pretende igualar la
  calidad semántica de un modelo de embeddings real.
"""
from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np

from app.config import Settings
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.rag.text import strip_accents, tokenize

log = get_logger(__name__)


class Embedder(Protocol):
    dimensions: int
    name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    name = "local-hashing-v1"

    def __init__(self, dimensions: int = 2048):
        self.dimensions = dimensions

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "little")
        return h % self.dimensions, (1.0 if (h >> 63) & 1 else -1.0)

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dimensions, dtype=np.float32)
        tokens = tokenize(text)
        feats: list[tuple[str, float]] = [(f"w:{t}", 1.0) for t in tokens]
        feats += [(f"b:{a}_{b}", 0.7) for a, b in zip(tokens, tokens[1:], strict=False)]
        for tok in tokens:  # trigramas de caracteres: robustez a variantes morfológicas/typos
            padded = f"#{strip_accents(tok)}#"
            feats += [(f"c:{padded[i:i + 3]}", 0.25) for i in range(len(padded) - 2)]
        for feat, weight in feats:
            idx, sign = self._bucket(feat)
            vec[idx] += sign * weight
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._vector(t) for t in texts]) if texts else np.zeros((0, self.dimensions), np.float32)


class AzureOpenAIEmbedder:
    def __init__(self, settings: Settings, client=None):
        from app.llm.azure_openai import build_azure_openai_client

        self.client = client or build_azure_openai_client(settings)
        self.deployment = settings.azure_openai_embedding_deployment
        self.dimensions = settings.embedding_dimensions
        self.name = f"azure-openai:{self.deployment}"

    def embed(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                resp = self.client.embeddings.create(model=self.deployment, input=batch, dimensions=self.dimensions)
            except Exception as exc:
                log.error("embedding_failed", extra={"batch": i, "error": type(exc).__name__})
                raise UpstreamError("Fallo generando embeddings en Azure OpenAI") from exc
            vectors.extend(d.embedding for d in resp.data)
        arr = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.where(norms == 0, 1, norms)


def build_embedder(settings: Settings) -> Embedder:
    if settings.llm_provider == "azure":
        return AzureOpenAIEmbedder(settings)
    return HashingEmbedder()
