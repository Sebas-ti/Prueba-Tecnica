"""Punto de entrada de la aplicación FastAPI."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import Settings, get_settings
from app.container import Container
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger, request_id_var
from app.core.telemetry import configure_telemetry

log = get_logger(__name__)

DESCRIPTION = """
Agente RAG empresarial para el sistema de **gestión de solicitudes internas**.

* **/v1/chat** — preguntas en lenguaje natural; el agente busca en la documentación
  (RAG híbrido) y usa herramientas (estado, prioridad, esfuerzo, resumen, servicios cloud).
* **/v1/documents** — carga y procesamiento de documentos (PDF, DOCX, MD, TXT).
* **/v1/history** — trazabilidad completa de interacciones.

Autenticación: cabecera `X-API-Key` (deshabilitada solo en `ENVIRONMENT=local`).
"""


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_telemetry(settings)
        app.state.container = container or Container.build(settings)
        if not settings.api_key_set:
            log.warning("auth_disabled", extra={"environment": settings.environment})
        if app.state.container.kb.store.count() == 0:
            log.warning("empty_index", extra={"hint": "POST /v1/documents/reindex o python -m scripts.ingest"})
        yield

    app = FastAPI(title=settings.app_name, version="1.0.0", description=DESCRIPTION, lifespan=lifespan)
    register_exception_handlers(app)

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                           allow_methods=["GET", "POST", "DELETE"], allow_headers=["X-API-Key", "Content-Type"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(rid[:64])
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed = int((time.perf_counter() - t0) * 1000)
        response.headers["X-Request-ID"] = rid[:64]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        token = request_id_var.set(rid[:64])
        log.info("http_request", extra={"method": request.method, "path": request.url.path,
                                        "status": response.status_code, "elapsed_ms": elapsed})
        request_id_var.reset(token)
        return response

    @app.get("/health", tags=["operación"], summary="Liveness")
    def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["operación"], summary="Readiness")
    def ready(request: Request):
        c: Container = request.app.state.container
        return {
            "status": "ready",
            "environment": settings.environment,
            "llm": c.agent.llm.model_name,
            "embeddings": c.kb.embedder.name,
            "vector_store": settings.vector_store_provider,
            "history": settings.history_provider,
            "indexed_chunks": c.kb.store.count(),
        }

    app.include_router(router)
    return app


app = create_app()
