"""Ingesta por lotes del corpus (útil en CI/CD o como Container Apps Job).

Uso:
    python -m scripts.ingest                 # ingesta data/docs
    python -m scripts.ingest --dir otra/ruta
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.config import get_settings
from app.core.logging import configure_logging
from app.rag.embeddings import build_embedder
from app.rag.knowledge_base import KnowledgeBase
from app.rag.vectorstore import build_vector_store


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Ingesta de documentos al vector store")
    parser.add_argument("--dir", default=str(Path(settings.data_dir) / "docs"))
    args = parser.parse_args()
    configure_logging("WARNING")
    kb = KnowledgeBase(settings, build_embedder(settings), build_vector_store(settings))
    reports = kb.ingest_directory(args.dir)
    print(json.dumps([asdict(r) for r in reports], indent=2, ensure_ascii=False))
    print(f"Total de chunks en el índice: {kb.store.count()}")


if __name__ == "__main__":
    main()
