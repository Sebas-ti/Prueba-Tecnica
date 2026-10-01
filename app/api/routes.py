"""Rutas HTTP de la API v1."""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.agent.tools import TOOLS
from app.api.deps import authenticate, get_app_settings, get_container, rate_limited
from app.api.schemas import ChatRequest, ChatResponse, DocumentInfo, FeedbackRequest, HistoryPage, IngestionResponse
from app.config import Settings
from app.container import Container
from app.core.errors import AppError, BadRequestError, NotFoundError, PayloadTooLargeError, UnsupportedFileError
from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/v1")

_SAFE_NAME = re.compile(r"^[\w\-. ()áéíóúñÁÉÍÓÚÑ]{1,120}$")
_MAGIC = {".pdf": b"%PDF", ".docx": b"PK\x03\x04"}


# ----------------------------------------------------------------- Chat
@router.post("/chat", response_model=ChatResponse, tags=["asistente"], summary="Consultar al asistente")
def chat(body: ChatRequest, client: str = Depends(rate_limited), c: Container = Depends(get_container)) -> ChatResponse:
    """Envía una pregunta al agente. Devuelve respuesta, fuentes citadas, herramientas usadas,
    evaluación de fundamentación y banderas de seguridad."""
    result = c.agent.run(body.question, session_id=body.session_id, user_id=client)
    return ChatResponse(**asdict(result))


@router.post("/feedback", tags=["trazabilidad"], summary="Registrar feedback (👍/👎) sobre una interacción")
def submit_feedback(body: FeedbackRequest, _: str = Depends(rate_limited), c: Container = Depends(get_container)):
    """Cierra el ciclo de evaluación con usuarios reales: asocia un rating a una
    interacción ya guardada en el historial (no crea una nueva)."""
    record = c.history.get(body.interaction_id)
    if not record:
        raise NotFoundError(f"No existe la interacción {body.interaction_id}")
    record["feedback"] = {"rating": body.rating, "comment": body.comment, "ts": datetime.now(UTC).isoformat()}
    c.history.save(record)
    return {"interaction_id": body.interaction_id, "feedback": record["feedback"]}


# ------------------------------------------------------------ Documentos
def _validate_upload(file: UploadFile, content: bytes, settings: Settings) -> str:
    name = Path(file.filename or "").name
    if not name or not _SAFE_NAME.match(name):
        raise BadRequestError("Nombre de archivo inválido")
    ext = Path(name).suffix.lower()
    if ext not in settings.allowed_extension_set:
        raise UnsupportedFileError(f"Extensión no permitida: {ext}", details={"allowed": sorted(settings.allowed_extension_set)})
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise PayloadTooLargeError(f"El archivo supera {settings.max_upload_mb} MB")
    if not content:
        raise BadRequestError("Archivo vacío")
    magic = _MAGIC.get(ext)
    if magic and not content.startswith(magic):
        raise UnsupportedFileError("El contenido no corresponde a la extensión declarada")
    return name


@router.post("/documents", response_model=IngestionResponse, tags=["documentos"], summary="Cargar y procesar documentos")
async def upload_documents(
    files: list[UploadFile] = File(..., description="Uno o más archivos .pdf, .docx, .md, .txt"),
    _: str = Depends(rate_limited),
    c: Container = Depends(get_container),
    settings: Settings = Depends(get_app_settings),
) -> IngestionResponse:
    """Ingesta: extracción de texto -> chunking -> embeddings -> vector store.
    Re-cargar un archivo con el mismo nombre reemplaza su versión anterior."""
    if len(files) > 20:
        raise BadRequestError("Máximo 20 archivos por petición")
    ingested, errors = [], []
    for f in files:
        content = await f.read(settings.max_upload_mb * 1024 * 1024 + 1)
        try:
            name = _validate_upload(f, content, settings)
            ingested.append(asdict(c.kb.ingest_bytes(name, content)))
        except AppError as exc:
            errors.append({"file": f.filename, "code": exc.code, "message": exc.message})
    if not ingested and errors:
        raise BadRequestError("Ningún archivo pudo procesarse", details={"errors": errors})
    return IngestionResponse(ingested=ingested, errors=errors, total_chunks_in_index=c.kb.store.count())


@router.post("/documents/reindex", response_model=IngestionResponse, tags=["documentos"], summary="Re-indexar el corpus base")
def reindex(_: str = Depends(rate_limited), c: Container = Depends(get_container), settings: Settings = Depends(get_app_settings)):
    reports = c.kb.ingest_directory(str(Path(settings.data_dir) / "docs"))
    return IngestionResponse(ingested=[asdict(r) for r in reports], total_chunks_in_index=c.kb.store.count())


@router.get("/documents", response_model=list[DocumentInfo], tags=["documentos"], summary="Listar documentos indexados")
def list_documents(_: str = Depends(authenticate), c: Container = Depends(get_container)):
    return c.kb.store.list_sources()


@router.delete("/documents/{source}", tags=["documentos"], summary="Eliminar un documento del índice")
def delete_document(source: str, _: str = Depends(rate_limited), c: Container = Depends(get_container)):
    removed = c.kb.store.delete_source(source)
    if not removed:
        raise NotFoundError(f"No existe el documento {source}")
    log.info("document_deleted", extra={"source": source, "chunks": removed})
    return {"source": source, "removed_chunks": removed}


# ------------------------------------------------------------- Historial
@router.get("/history", response_model=HistoryPage, tags=["trazabilidad"], summary="Consultar historial de interacciones")
def list_history(
    limit: int = Query(20, ge=1, le=200),
    session_id: str | None = Query(None, pattern=r"^[A-Za-z0-9_-]{6,64}$"),
    status: str | None = Query(None, pattern=r"^(answered|no_info|blocked|output_blocked|incomplete)$"),
    _: str = Depends(authenticate),
    c: Container = Depends(get_container),
):
    items = c.history.list(limit=limit, session_id=session_id, status=status)
    return HistoryPage(items=items, count=len(items))


@router.get("/history/stats", tags=["trazabilidad"], summary="Métricas agregadas del historial")
def history_stats(_: str = Depends(authenticate), c: Container = Depends(get_container)):
    return c.history.stats()


@router.get("/history/{interaction_id}", tags=["trazabilidad"], summary="Detalle de una interacción")
def get_interaction(interaction_id: str, _: str = Depends(authenticate), c: Container = Depends(get_container)):
    item = c.history.get(interaction_id)
    if not item:
        raise NotFoundError("Interacción no encontrada")
    return item


# ----------------------------------------------------------- Herramientas
@router.get("/tools", tags=["asistente"], summary="Herramientas disponibles para el agente")
def list_tools(_: str = Depends(authenticate)):
    return [t.schema()["function"] for t in TOOLS.values()]
