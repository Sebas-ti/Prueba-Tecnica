"""Servicio de base de conocimiento: ingesta y recuperación."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.core.logging import get_logger
from app.core.security import neutralize_context
from app.rag.chunking import Chunk, chunk_text
from app.rag.embeddings import Embedder
from app.rag.loaders import load_bytes
from app.rag.text import tokenize
from app.rag.vectorstore import SearchResult, VectorStore

log = get_logger(__name__)


@dataclass
class IngestionReport:
    source: str
    chunks: int
    replaced_chunks: int
    flagged_chunks: int
    embedding_model: str
    elapsed_ms: int


class KnowledgeBase:
    def __init__(self, settings: Settings, embedder: Embedder, store: VectorStore):
        self.settings = settings
        self.embedder = embedder
        self.store = store

    # Ingesta ----------------------------------------------------------------
    def ingest_bytes(self, filename: str, content: bytes) -> IngestionReport:
        t0 = time.perf_counter()
        source = Path(filename).name
        sections = load_bytes(source, content)
        title = Path(source).stem.replace("_", " ").replace("-", " ").strip()
        chunks: list[Chunk] = []
        flagged = 0
        for section in sections:
            new = chunk_text(
                section.text, source=source, chunk_size=self.settings.chunk_size,
                chunk_overlap=self.settings.chunk_overlap, page=section.page,
                start_index=len(chunks), doc_title=title,
            )
            for c in new:
                # Inyección indirecta: se neutraliza en la ingesta (y otra vez
                # al construir el prompt) para que el índice no la propague.
                clean, was_flagged = neutralize_context(c.text)
                if was_flagged:
                    flagged += 1
                    c.text = clean
                    c.metadata["injection_flagged"] = True
            chunks.extend(new)
        if not chunks:
            from app.core.errors import BadRequestError

            raise BadRequestError("El documento no contiene texto indexable")
        vectors = self.embedder.embed([c.text for c in chunks])
        # Re-ingesta idempotente: se reemplaza la versión anterior del documento.
        replaced = self.store.delete_source(source)
        self.store.upsert(chunks, vectors)
        report = IngestionReport(
            source=source, chunks=len(chunks), replaced_chunks=replaced, flagged_chunks=flagged,
            embedding_model=self.embedder.name, elapsed_ms=int((time.perf_counter() - t0) * 1000),
        )
        log.info("document_ingested", extra=report.__dict__)
        if flagged:
            log.warning("indirect_injection_flagged", extra={"source": source, "chunks": flagged})
        return report

    def ingest_directory(self, directory: str) -> list[IngestionReport]:
        reports = []
        for path in sorted(Path(directory).glob("**/*")):
            if path.is_file() and path.suffix.lower() in self.settings.allowed_extension_set:
                reports.append(self.ingest_bytes(path.name, path.read_bytes()))
        return reports

    # Recuperación -----------------------------------------------------------
    def retrieve(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        t0 = time.perf_counter()
        qvec = self.embedder.embed([query])[0]
        results = self.store.search(query, qvec, top_k or self.settings.top_k)
        log.info(
            "retrieval",
            extra={
                "top_k": top_k or self.settings.top_k,
                "hits": [{"source": r.source, "chunk": r.chunk_index, "score": r.score} for r in results],
                "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            },
        )
        return results

    def relevant(self, results: list[SearchResult]) -> list[SearchResult]:
        """Umbral en dos pasos: la consulta debe tener al menos un resultado por encima
        de `min_relevance_score` (si no, no hay contexto suficiente); superado ese
        gate, se aceptan también resultados cercanos (>= 80 % del umbral) para no
        perder chunks largos y relevantes cuya similitud se diluye."""
        if not results or max(r.score for r in results) < self.settings.min_relevance_score:
            return []
        floor = self.settings.min_relevance_score * 0.8
        return [r for r in results if r.score >= floor]

    def query_coverage(self, query: str, results: list[SearchResult]) -> float | None:
        """Proporción (ponderada por IDF) de los términos de la consulta presentes en
        el contexto recuperado. Señal de "respondibilidad": una pregunta con términos
        clave ausentes del contexto (p. ej. "marketing") probablemente no tiene
        respuesta en las fuentes. Solo disponible con el store local (requiere IDF)."""
        idf = getattr(self.store, "idf", None)
        if idf is None:
            return None
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return 0.0
        ctx = set(tokenize(" ".join(r.text for r in results)))
        weights = {t: idf(t) for t in q_tokens}
        total = sum(weights.values()) or 1.0
        return round(sum(w for t, w in weights.items() if t in ctx) / total, 3)
