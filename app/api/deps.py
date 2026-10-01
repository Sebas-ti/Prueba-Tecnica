"""Dependencias de FastAPI: autenticación por API key y rate limiting."""
from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, Header, Request

from app.config import Settings
from app.container import Container
from app.core.errors import AppError, RateLimitError
from app.core.logging import get_logger

log = get_logger(__name__)


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_app_settings(request: Request) -> Settings:
    return request.app.state.container.settings


def authenticate(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_app_settings),
) -> str:
    """Devuelve un identificador de cliente (hash de la clave, nunca la clave)."""
    keys = settings.api_key_set
    if not keys:
        return "local-dev"  # solo posible en environment=local/test (validado en config)
    if not x_api_key or not any(hmac.compare_digest(x_api_key, k) for k in keys):
        raise UnauthorizedError("API key ausente o inválida")
    return "client-" + hashlib.sha256(x_api_key.encode()).hexdigest()[:10]


class _RateLimiter:
    """Ventana deslizante en memoria. En producción: Azure API Management (rate-limit-by-key)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, client: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[client]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                raise RateLimitError("Límite de peticiones excedido", details={"limit_per_minute": limit})
            q.append(now)


_limiter = _RateLimiter()


def rate_limited(client: str = Depends(authenticate), settings: Settings = Depends(get_app_settings)) -> str:
    _limiter.check(client, settings.rate_limit_per_minute)
    return client
