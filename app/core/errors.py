"""Errores de dominio y su traducción a respuestas HTTP homogéneas."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_var

log = get_logger(__name__)


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class UnsupportedFileError(AppError):
    status_code = 415
    code = "unsupported_file"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class UpstreamError(AppError):
    """Falla de un servicio externo (Azure OpenAI, AI Search, Cosmos)."""

    status_code = 502
    code = "upstream_error"


class ContentFilteredError(AppError):
    """Azure OpenAI rechazó la petición por su filtro de contenido (incluye jailbreak).

    Es la segunda capa de defensa (la heurística propia es la primera). El agente la
    captura y la traduce a un resultado normal con status=blocked; no debería llegar
    sin capturar hasta la respuesta HTTP, pero se deja un status_code de respaldo.
    """

    status_code = 502
    code = "content_filtered"


class UpstreamRateLimitError(AppError):
    """Azure OpenAI está limitando la tasa de peticiones (cuota de TPM/RPM)."""

    status_code = 503
    code = "upstream_rate_limited"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


def _body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}, "request_id": request_id_var.get()}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        level = log.error if exc.status_code >= 500 else log.warning
        level("app_error", extra={"code": exc.code, "status": exc.status_code, "detail": exc.message})
        headers = None
        retry_after = exc.details.get("retry_after")
        if retry_after is not None:
            headers = {"Retry-After": str(retry_after)}
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        log.warning("validation_error", extra={"errors": errors})
        return JSONResponse(status_code=422, content=_body("validation_error", "Entrada inválida", {"errors": errors}))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Nunca se devuelve el stacktrace al cliente: solo se registra.
        log.exception("unhandled_error")
        return JSONResponse(status_code=500, content=_body("internal_error", "Error interno. Use el request_id para soporte."))
