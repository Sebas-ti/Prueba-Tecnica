"""Vector stores con búsqueda híbrida (vectorial + léxica).

- `LocalVectorStore`: numpy + BM25, fusionados con Reciprocal Rank Fusion (RRF).
  Persiste en disco (npz + json). Adecuado para desarrollo, demo y pruebas.
- `AzureSearchVectorStore`: Azure AI Search con índice HNSW, búsqueda híbrida
  nativa (BM25 + vector con RRF) y re-ranking semántico opcional.

Ambos exponen la misma interfaz, por lo que el resto del código no sabe cuál se
usa (puerto/adaptador).
"""
from __future__ import annotations

import json
import math
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from app.config import Settings
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.rag.chunking import Chunk
from app.rag.text import tokenize

log = get_logger(__name__)


@dataclass
class SearchResult:
    id: str
    text: str
    source: str
    section: str
    page: int | None
    chunk_index: int
    score: float  # relevancia normalizada 0..1 usada para el umbral de "sin información"
    vector_score: float | None = None
    keyword_score: float | None = None


class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], vectors: np.ndarray) -> int: ...
    def delete_source(self, source: str) -> int: ...
    def search(self, query: str, query_vector: np.ndarray, top_k: int) -> list[SearchResult]: ...
    def list_sources(self) -> list[dict]: ...
    def count(self) -> int: ...


# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------
class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.doc_len = np.array([len(d) for d in docs], dtype=np.float32)
        self.avgdl = float(self.doc_len.mean()) if docs else 0.0
        self.tf = [Counter(d) for d in docs]
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.docs), dtype=np.float32)
        for i, tf in enumerate(self.tf):
            s = 0.0
            for q in query:
                f = tf.get(q)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avgdl or 1))
                s += self.idf.get(q, 0.0) * f * (self.k1 + 1) / denom
            out[i] = s
        return out


class LocalVectorStore:
    RRF_K = 60

    def __init__(self, index_dir: str):
        self.dir = Path(index_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.chunks: list[dict] = []
        self.vectors: np.ndarray | None = None
        self._bm25: _BM25 | None = None
        self._load()

    # Persistencia ---------------------------------------------------------
    def _load(self) -> None:
        meta, vec = self.dir / "chunks.json", self.dir / "vectors.npy"
        if meta.exists() and vec.exists():
            self.chunks = json.loads(meta.read_text(encoding="utf-8"))
            self.vectors = np.load(vec)
            self._rebuild_bm25()
            log.info("local_index_loaded", extra={"chunks": len(self.chunks)})

    def _save(self) -> None:
        (self.dir / "chunks.json").write_text(json.dumps(self.chunks, ensure_ascii=False), encoding="utf-8")
        if self.vectors is not None:
            np.save(self.dir / "vectors.npy", self.vectors)

    def _rebuild_bm25(self) -> None:
        self._bm25 = _BM25([tokenize(c["text"]) for c in self.chunks]) if self.chunks else None

    # Operaciones ------------------------------------------------------------
    def upsert(self, chunks: list[Chunk], vectors: np.ndarray) -> int:
        with self._lock:
            existing = {c["id"]: i for i, c in enumerate(self.chunks)}
            new_rows, new_vecs = [], []
            for chunk, vec in zip(chunks, vectors, strict=True):
                row = chunk.to_dict()
                if chunk.id in existing:
                    i = existing[chunk.id]
                    self.chunks[i] = row
                    self.vectors[i] = vec
                else:
                    new_rows.append(row)
                    new_vecs.append(vec)
            if new_rows:
                stacked = np.vstack(new_vecs).astype(np.float32)
                self.vectors = stacked if self.vectors is None or len(self.vectors) == 0 else np.vstack([self.vectors, stacked])
                self.chunks.extend(new_rows)
            self._rebuild_bm25()
            self._save()
            return len(chunks)

    def delete_source(self, source: str) -> int:
        with self._lock:
            keep = [i for i, c in enumerate(self.chunks) if c["source"] != source]
            removed = len(self.chunks) - len(keep)
            if removed:
                self.chunks = [self.chunks[i] for i in keep]
                self.vectors = self.vectors[keep] if self.vectors is not None and keep else None
                self._rebuild_bm25()
                self._save()
            return removed

    def search(self, query: str, query_vector: np.ndarray, top_k: int) -> list[SearchResult]:
        with self._lock:
            if not self.chunks or self.vectors is None:
                return []
            cos = self.vectors @ query_vector.astype(np.float32)
            bm25 = self._bm25.scores(tokenize(query)) if self._bm25 else np.zeros(len(self.chunks))
            n_candidates = min(len(self.chunks), max(top_k * 4, 20))
            vec_rank = np.argsort(-cos)[:n_candidates]
            kw_rank = [i for i in np.argsort(-bm25)[:n_candidates] if bm25[i] > 0]
            fused: dict[int, float] = {}
            for rank, i in enumerate(vec_rank):
                fused[int(i)] = fused.get(int(i), 0) + 1 / (self.RRF_K + rank + 1)
            for rank, i in enumerate(kw_rank):
                fused[int(i)] = fused.get(int(i), 0) + 1 / (self.RRF_K + rank + 1)
            ordered = sorted(fused, key=fused.get, reverse=True)[:top_k]
            max_bm25 = float(bm25.max()) if len(bm25) else 0.0
            results = []
            for i in ordered:
                c = self.chunks[i]
                # Relevancia: combinación de similitud coseno y BM25 normalizado
                # por el máximo teórico aproximado. Solo se usa para decidir si
                # hay contexto suficiente; el orden lo define RRF.
                kw_norm = float(bm25[i]) / (max_bm25 + 5.0) if max_bm25 > 0 else 0.0
                relevance = float(np.clip(0.6 * max(float(cos[i]), 0.0) + 0.4 * kw_norm, 0, 1))
                results.append(
                    SearchResult(
                        id=c["id"], text=c["text"], source=c["source"], section=c.get("section", ""),
                        page=c.get("page"), chunk_index=c["chunk_index"], score=round(relevance, 4),
                        vector_score=round(float(cos[i]), 4), keyword_score=round(float(bm25[i]), 4),
                    )
                )
            return results

    def list_sources(self) -> list[dict]:
        with self._lock:
            counts = Counter(c["source"] for c in self.chunks)
            return [{"source": s, "chunks": n} for s, n in sorted(counts.items())]

    def idf(self, token: str) -> float:
        """IDF del término en el corpus; un término ausente recibe el IDF máximo."""
        n = len(self.chunks)
        oov = math.log(1 + (n + 0.5) / 0.5)
        return self._bm25.idf.get(token, oov) if self._bm25 else oov

    def count(self) -> int:
        return len(self.chunks)


# ---------------------------------------------------------------------------
# Azure AI Search
# ---------------------------------------------------------------------------
class AzureSearchVectorStore:
    def __init__(self, settings: Settings):
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient
        from azure.search.documents.indexes import SearchIndexClient

        if settings.azure_search_api_key:
            credential = AzureKeyCredential(settings.azure_search_api_key.get_secret_value())
        else:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self.settings = settings
        self.index_name = settings.azure_search_index
        self.index_client = SearchIndexClient(settings.azure_search_endpoint, credential)
        self.client = SearchClient(settings.azure_search_endpoint, self.index_name, credential)
        self._ensure_index()

    def _ensure_index(self) -> None:
        from azure.core.exceptions import ResourceNotFoundError
        from azure.search.documents.indexes.models import (
            HnswAlgorithmConfiguration,
            SearchableField,
            SearchField,
            SearchFieldDataType,
            SearchIndex,
            SemanticConfiguration,
            SemanticField,
            SemanticPrioritizedFields,
            SemanticSearch,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        try:
            self.index_client.get_index(self.index_name)
            return
        except ResourceNotFoundError:
            pass
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="es.microsoft"),
            SimpleField(name="source", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SearchableField(name="section", type=SearchFieldDataType.String, analyzer_name="es.microsoft"),
            SimpleField(name="page", type=SearchFieldDataType.Int32, filterable=True),
            SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, sortable=True),
            SearchField(
                name="embedding",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.settings.embedding_dimensions,
                vector_search_profile_name="hnsw-profile",
            ),
        ]
        index = SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=VectorSearch(
                algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
                profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
            ),
            semantic_search=SemanticSearch(
                configurations=[
                    SemanticConfiguration(
                        name="default",
                        prioritized_fields=SemanticPrioritizedFields(
                            title_field=SemanticField(field_name="section"),
                            content_fields=[SemanticField(field_name="content")],
                        ),
                    )
                ]
            ),
        )
        self.index_client.create_or_update_index(index)
        log.info("azure_search_index_created", extra={"index": self.index_name})

    def upsert(self, chunks: list[Chunk], vectors: np.ndarray) -> int:
        docs = [
            {"id": c.id, "content": c.text, "source": c.source, "section": c.section, "page": c.page,
             "chunk_index": c.chunk_index, "embedding": v.tolist()}
            for c, v in zip(chunks, vectors, strict=True)
        ]
        try:
            for i in range(0, len(docs), 500):
                self.client.merge_or_upload_documents(docs[i : i + 500])
        except Exception as exc:
            raise UpstreamError("Fallo indexando en Azure AI Search") from exc
        return len(docs)

    def delete_source(self, source: str) -> int:
        safe = source.replace("'", "''")
        ids = [{"id": d["id"]} for d in self.client.search(search_text="*", filter=f"source eq '{safe}'", select=["id"])]
        if ids:
            self.client.delete_documents(ids)
        return len(ids)

    def search(self, query: str, query_vector: np.ndarray, top_k: int) -> list[SearchResult]:
        from azure.search.documents.models import VectorizedQuery

        vq = VectorizedQuery(vector=query_vector.tolist(), k_nearest_neighbors=max(top_k * 3, 10), fields="embedding")
        try:
            results = self.client.search(
                search_text=query,
                vector_queries=[vq],
                query_type="semantic",
                semantic_configuration_name="default",
                top=top_k,
                select=["id", "content", "source", "section", "page", "chunk_index"],
            )
            out = []
            for r in results:
                # El reranker semántico devuelve 0..4; se normaliza a 0..1.
                reranker = r.get("@search.reranker_score")
                score = (reranker / 4.0) if reranker is not None else float(r.get("@search.score", 0))
                out.append(
                    SearchResult(id=r["id"], text=r["content"], source=r["source"], section=r.get("section") or "",
                                 page=r.get("page"), chunk_index=r.get("chunk_index") or 0, score=round(score, 4),
                                 keyword_score=r.get("@search.score"))
                )
            return out
        except Exception as exc:
            raise UpstreamError("Fallo consultando Azure AI Search") from exc

    def list_sources(self) -> list[dict]:
        res = self.client.search(search_text="*", facets=["source,count:1000"], top=0)
        return [{"source": f["value"], "chunks": f["count"]} for f in (res.get_facets() or {}).get("source", [])]

    def count(self) -> int:
        return self.client.get_document_count()


def build_vector_store(settings: Settings) -> VectorStore:
    if settings.vector_store_provider == "azure_search":
        return AzureSearchVectorStore(settings)
    return LocalVectorStore(settings.index_dir)
